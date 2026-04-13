"""Pipeline — the state machine that drives each issue through stages."""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Callable
import logging
import os
import time

from aiorchestra.ai import agent_family_from_config, build_agent_branch, provider_for_agent
from aiorchestra.ai._agents import KNOWN_AGENTS
from aiorchestra.config import _deep_merge, load_config
from aiorchestra.stages._shell import StageTimer, has_diff_from_main, run_command
from aiorchestra.stages.clarification import request_clarification
from aiorchestra.stages.discover import discover_issues
from aiorchestra.stages.osint import enrich_issue
from aiorchestra.stages.ci import wait_for_ci
from aiorchestra.stages.implement import implement
from aiorchestra.stages.labels import (
    LABEL_AWAITING_REVIEW,
    LABEL_FAILED,
    LABEL_WORKING,
    add_label,
    ensure_labels,
    remove_label,
    swap_label,
)
from aiorchestra.stages.prepare import prepare_environment
from aiorchestra.stages.publish import publish
from aiorchestra.stages.review import review
from aiorchestra.stages.types import IssueData, PipelineConfig, RemoteCheckFn
from aiorchestra.stages.validate import validate

log = logging.getLogger(__name__)

# Sentinel: issue was deferred (not a failure — just waiting for human input).
_DEFERRED = "deferred"


def _fmt_duration(seconds: float) -> str:
    """Format a duration in seconds for human-readable log output."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}m{secs:02d}s"


def _has_changes(repo_root: str) -> bool:
    """Return True if the worktree has any uncommitted or staged changes."""
    result = run_command(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        logger=log,
    )
    return bool(result.stdout.strip())


def _branch_has_existing_work(repo_root: str) -> bool:
    """Return True if the current branch has commits ahead of origin/main."""
    return has_diff_from_main(repo_root)


@dataclass(frozen=True)
class _IssueContext:
    repo: str
    branch: str
    issue: IssueData
    config: PipelineConfig
    repo_root: str
    osint_context: str = ""

    @property
    def max_retries(self) -> int:
        return self.config.get("ai", {}).get("max_retries", 3)


class Pipeline:
    def __init__(
        self,
        repo: str,
        label: str,
        config: PipelineConfig,
        config_path: str | None = None,
        issue_number: int | None = None,
        dry_run: bool = False,
        workspace: str | None = None,
        parallel: bool = True,
        review_only: bool = False,
    ):
        self.repo = repo
        self.label = label
        self.issue_number = issue_number
        self.config = config
        self.config_path = config_path
        self.dry_run = dry_run
        self.workspace = workspace
        self.parallel = parallel
        self.review_only = review_only

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, issues: list[IssueData] | None = None) -> int:
        """Run the full pipeline. Returns 0 on success, 1 on failure."""
        ensure_labels(self.repo, dry_run=self.dry_run)

        if issues is None:
            issues = discover_issues(
                self.repo,
                self.label,
                self.issue_number,
                agent_label=agent_family_from_config(self.config),
            )
        if not issues:
            log.info("No issues found.")
            return 0

        if self.parallel:
            return self._run_parallel(issues)
        return self._run_sequential(issues)

    # ------------------------------------------------------------------
    # Sequential mode (original behaviour, useful for single-issue runs)
    # ------------------------------------------------------------------

    def _run_sequential(self, issues: list[IssueData]) -> int:
        for issue in issues:
            log.info("Processing issue #%d: %s", issue["number"], issue["title"])
            if self.dry_run:
                log.info("[dry-run] Would process issue #%d", issue["number"])
                continue

            result = self._claim_and_process(issue)
            if result == _DEFERRED:
                continue
            if not result:
                return 1

        return 0

    # ------------------------------------------------------------------
    # Parallel mode — one forked child per issue
    # ------------------------------------------------------------------

    def _run_parallel(self, issues: list[IssueData]) -> int:
        """Fork a child process for each issue.

        The parent claims the issue (adds ``agent-working`` label), forks,
        and moves on to the next issue.  Each child processes exactly one
        issue and calls ``os._exit``.  The parent waits for all children
        before returning.
        """
        children: list[tuple[int, int]] = []  # (pid, issue_number)

        for issue in issues:
            log.info("Processing issue #%d: %s", issue["number"], issue["title"])
            if self.dry_run:
                log.info("[dry-run] Would process issue #%d", issue["number"])
                continue

            # Claim before forking so discovery in other runners sees it.
            add_label(self.repo, issue["number"], LABEL_WORKING)

            pid = os.fork()

            if pid > 0:
                # Parent — record child and move to next issue.
                log.info(
                    "Forked child %d for issue #%d",
                    pid,
                    issue["number"],
                )
                children.append((pid, issue["number"]))
                continue

            # ---- child process ----
            self._child_main(issue)
            # _child_main never returns

        return self._wait_for_children(children)

    def _child_main(self, issue: IssueData) -> None:
        """Entry point for a forked child — processes one issue then exits."""
        number = issue["number"]
        try:
            result = self._process_issue(issue)

            if result == _DEFERRED:
                log.info("Issue #%d deferred — waiting for clarification", number)
                remove_label(self.repo, number, LABEL_WORKING)
                os._exit(0)

            if not result:
                log.error("Failed to process issue #%d", number)
                swap_label(self.repo, number, LABEL_WORKING, LABEL_FAILED)
                os._exit(1)

            swap_label(self.repo, number, LABEL_WORKING, LABEL_AWAITING_REVIEW)
            os._exit(0)

        except Exception:
            log.exception("Unhandled error processing issue #%d", number)
            swap_label(self.repo, number, LABEL_WORKING, LABEL_FAILED)
            os._exit(1)

    @staticmethod
    def _wait_for_children(children: list[tuple[int, int]]) -> int:
        """Wait for all child processes. Returns 0 if all succeeded."""
        failed = []
        for pid, number in children:
            try:
                _, status = os.waitpid(pid, 0)
                exit_code = os.waitstatus_to_exitcode(status)
            except ChildProcessError:
                log.warning("Child %d (issue #%d) already reaped", pid, number)
                continue

            if exit_code != 0:
                log.error(
                    "Child %d (issue #%d) exited with code %d",
                    pid,
                    number,
                    exit_code,
                )
                failed.append(number)
            else:
                log.info("Child %d (issue #%d) completed successfully", pid, number)

        if failed:
            log.error("Issues that failed: %s", failed)
            return 1
        return 0

    # ------------------------------------------------------------------
    # Core issue processing (runs in the child when parallel=True)
    # ------------------------------------------------------------------

    def _claim_and_process(self, issue: IssueData) -> bool | str:
        """Claim an issue, process it, and release the claim."""
        number = issue["number"]
        add_label(self.repo, number, LABEL_WORKING)
        try:
            result = self._process_issue(issue)
        except Exception:
            log.exception("Unhandled error processing issue #%d", number)
            swap_label(self.repo, number, LABEL_WORKING, LABEL_FAILED)
            return False

        if result == _DEFERRED:
            log.info("Issue #%d deferred — waiting for clarification", number)
            remove_label(self.repo, number, LABEL_WORKING)
            return _DEFERRED

        if not result:
            log.error("Failed to process issue #%d", number)
            swap_label(self.repo, number, LABEL_WORKING, LABEL_FAILED)
        else:
            swap_label(self.repo, number, LABEL_WORKING, LABEL_AWAITING_REVIEW)
        return result

    def _process_issue(self, issue: IssueData) -> bool | str:
        """Process a single issue. Returns True on success, False on failure,
        or ``_DEFERRED`` when the issue needs human clarification."""
        if self.review_only:
            return self._process_issue_review_only(issue)

        timer = StageTimer()

        with timer.step("prepare"):
            ctx = self._prepare_issue(issue)
        log.info("[prepare] completed in %s", _fmt_duration(timer._steps["prepare"]))
        if ctx is None:
            return False

        if _branch_has_existing_work(ctx.repo_root):
            log.info("Branch has existing work — using rework mode")
            initial_prompt = "rework"
        else:
            initial_prompt = "implement"

        with timer.step("impl+validate"):
            loop_result = self._run_validation_loop(ctx, prompt_name=initial_prompt)
        if loop_result == _DEFERRED:
            return _DEFERRED
        if not loop_result:
            return False

        with timer.step("publish"):
            pr_url = publish(
                ctx.repo,
                ctx.branch,
                ctx.issue,
                repo_root=ctx.repo_root,
            )
        log.info("[publish] completed in %s", _fmt_duration(timer._steps["publish"]))
        if not pr_url:
            return False

        with timer.step("ci"):
            pr_url = self._run_ci_fix_loop(ctx, pr_url)
        if not pr_url:
            return False

        with timer.step("review"):
            pr_url = self._run_review_fix_loop(ctx, pr_url)
        if not pr_url:
            return False

        log.info(
            "Issue #%d total: %s (%s)",
            issue["number"],
            _fmt_duration(timer.total),
            ", ".join(f"{k}: {_fmt_duration(v)}" for k, v in timer._steps.items()),
        )
        log.info("Issue #%d completed successfully.", issue["number"])
        return True

    def _process_issue_review_only(self, issue: IssueData) -> bool:
        """Review-only mode: validate and review existing work without implementing.

        Skips implementation, publishing, and CI — just runs validation and
        the review tiers on whatever code is already on the branch.
        """
        issue_start = time.monotonic()
        log.info("Review-only mode for issue #%d", issue["number"])

        t0 = time.monotonic()
        ctx = self._prepare_issue(issue)
        prepare_elapsed = time.monotonic() - t0
        log.info("[prepare] completed in %s", _fmt_duration(prepare_elapsed))
        if ctx is None:
            return False

        if not _branch_has_existing_work(ctx.repo_root):
            log.error("Review-only mode requires existing work on the branch")
            return False

        passed = True

        # Run validation (tests, lint, static analysis).
        t0 = time.monotonic()
        val_ok, val_feedback = validate(ctx.config, repo_root=ctx.repo_root)
        validate_elapsed = time.monotonic() - t0
        log.info("[validate] completed in %s", _fmt_duration(validate_elapsed))
        if not val_ok:
            log.warning("Validation failed: %.500s", val_feedback)
            passed = False

        # Run review tiers.
        t0 = time.monotonic()
        rev_ok, rev_feedback = review(
            ctx.repo,
            ctx.branch,
            ctx.config,
            issue=ctx.issue,
            repo_root=ctx.repo_root,
        )
        review_elapsed = time.monotonic() - t0
        log.info("[review] completed in %s", _fmt_duration(review_elapsed))
        if not rev_ok:
            log.warning("Review failed: %.500s", rev_feedback)
            passed = False

        total_elapsed = time.monotonic() - issue_start
        status = "PASSED" if passed else "FAILED"
        log.info(
            "Review-only #%d %s — total: %s (prepare: %s, validate: %s, review: %s)",
            issue["number"],
            status,
            _fmt_duration(total_elapsed),
            _fmt_duration(prepare_elapsed),
            _fmt_duration(validate_elapsed),
            _fmt_duration(review_elapsed),
        )
        return passed

    def _prepare_issue(self, issue: IssueData) -> _IssueContext | None:
        branch = build_agent_branch(self.config, issue["number"])
        repo_root = prepare_environment(self.repo, branch, self.workspace)
        if not repo_root:
            return None

        log.info("Working in %s", repo_root)
        config = load_config(self.config_path, repo_root=repo_root)

        # Override the AI provider when the pipeline label indicates a
        # specific agent family (e.g. issue labelled "codex" must use
        # the codex provider, not the default from config).
        if self.label and self.label in KNOWN_AGENTS:
            expected_provider = provider_for_agent(self.label)
            ai_section = config.get("ai", {})
            if ai_section.get("provider", "claude-code") != expected_provider:
                log.info(
                    "Overriding provider %s -> %s (label=%s)",
                    ai_section.get("provider", "claude-code"),
                    expected_provider,
                    self.label,
                )
                config = _deep_merge(config, {"ai": {"provider": expected_provider}})

        # Log resolved config at startup.
        ai_cfg = config.get("ai", {})
        review_cfg = config.get("review", {})
        ci_cfg = config.get("ci", {})
        enabled_tiers = [
            t.get("name", "?") for t in review_cfg.get("tiers", []) if t.get("enabled", False)
        ]
        log.info(
            "Config: provider=%s model=%s review=%s ci_timeout=%ss",
            ai_cfg.get("provider", "claude-code"),
            ai_cfg.get("model", "default"),
            enabled_tiers or "(legacy)",
            ci_cfg.get("timeout", 600),
        )
        # OSINT enrichment — runs locally, zero cloud tokens.
        osint_config = config.get("osint", {})
        osint_context = enrich_issue(issue, osint_config)
        if osint_context:
            log.info("OSINT enrichment produced %d bytes of context", len(osint_context))

        return _IssueContext(
            repo=self.repo,
            branch=branch,
            issue=issue,
            config=config,
            repo_root=repo_root,
            osint_context=osint_context,
        )

    def _run_validation_loop(
        self,
        ctx: _IssueContext,
        prompt_name: str = "implement",
        error_text: str | None = None,
        attempt_label: str = "Implementation",
    ) -> bool | str:
        """Returns True on success, False on failure, or _DEFERRED."""
        validation_errors = error_text
        current_prompt = prompt_name

        for attempt in range(1, ctx.max_retries + 1):
            log.info("%s attempt %d/%d", attempt_label, attempt, ctx.max_retries)

            t0 = time.monotonic()
            impl_result = self._implement(
                ctx,
                prompt_name=current_prompt,
                error_text=validation_errors,
            )
            log.info(
                "[implement] attempt %d completed in %s",
                attempt,
                _fmt_duration(time.monotonic() - t0),
            )
            if impl_result == _DEFERRED:
                return _DEFERRED
            if not impl_result:
                return False

            # Invariant 2: never proceed past implementation with zero file
            # changes.  Validation on an unmodified worktree is a false positive.
            if not _has_changes(ctx.repo_root):
                log.error("AI agent produced no file changes — aborting")
                return False

            ok, validation_errors = validate(ctx.config, repo_root=ctx.repo_root)
            if ok:
                return True

            current_prompt = "fix_validation"

        log.error("%s failed after %d attempts", attempt_label, ctx.max_retries)
        return False

    def _run_ci_fix_loop(self, ctx: _IssueContext, pr_url: str) -> str | None:
        if not ctx.config.get("ci", {}).get("enabled", True):
            return pr_url

        return self._run_remote_fix_loop(
            ctx,
            pr_url,
            stage_name="CI",
            prompt_name="fix_ci",
            check_fn=lambda current_pr_url: wait_for_ci(current_pr_url, ctx.config),
        )

    def _run_review_fix_loop(self, ctx: _IssueContext, pr_url: str) -> str | None:
        if not ctx.config.get("review", {}).get("enabled", True):
            return pr_url

        ci_enabled = ctx.config.get("ci", {}).get("enabled", True)

        def post_publish_ci_gate(current_pr_url: str) -> str | None:
            if not ci_enabled:
                return current_pr_url
            log.info("[review] Running post-publish CI verification")
            return self._run_ci_fix_loop(ctx, current_pr_url)

        return self._run_remote_fix_loop(
            ctx,
            pr_url,
            stage_name="Review",
            prompt_name="fix_review",
            check_fn=lambda current_pr_url: review(
                ctx.repo,
                ctx.branch,
                ctx.config,
                issue=ctx.issue,
                repo_root=ctx.repo_root,
            ),
            post_publish_fn=post_publish_ci_gate,
        )

    def _run_remote_fix_loop(
        self,
        ctx: _IssueContext,
        pr_url: str,
        stage_name: str,
        prompt_name: str,
        check_fn: RemoteCheckFn,
        post_publish_fn: Callable[[str], str | None] | None = None,
    ) -> str | None:
        for attempt in range(1, ctx.max_retries + 1):
            ok, feedback = check_fn(pr_url)
            if ok:
                return pr_url

            log.info("%s failed, attempt %d/%d", stage_name, attempt, ctx.max_retries)
            if feedback:
                log.info("%s feedback (first 500 chars): %.500s", stage_name, feedback)
                log.debug("%s full feedback: %s", stage_name, feedback)
            if not self._run_validation_loop(
                ctx,
                prompt_name=prompt_name,
                error_text=feedback,
                attempt_label=f"{stage_name} remediation",
            ):
                return None

            pr_url = publish(
                ctx.repo,
                ctx.branch,
                ctx.issue,
                repo_root=ctx.repo_root,
                pr_url=pr_url,
            )
            if not pr_url:
                return None

            if post_publish_fn is not None:
                pr_url = post_publish_fn(pr_url)
                if not pr_url:
                    return None

        log.error("%s failed after %d attempts", stage_name, ctx.max_retries)
        return None

    def _implement(
        self,
        ctx: _IssueContext,
        prompt_name: str,
        error_text: str | None = None,
    ) -> bool | str:
        """Returns True on success, False on failure, or _DEFERRED."""
        result = implement(
            ctx.issue,
            ctx.config,
            prompt_name=prompt_name,
            error_text=error_text,
            repo_root=ctx.repo_root,
            osint_context=ctx.osint_context,
            repo=ctx.repo,
        )

        if result.needs_clarification:
            log.info(
                "Agent requested clarification for issue #%d",
                ctx.issue["number"],
            )
            request_clarification(
                ctx.repo,
                ctx.issue,
                result.clarification_message,
            )
            return _DEFERRED

        return result.success
