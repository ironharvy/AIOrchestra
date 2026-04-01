"""Pipeline — the state machine that drives each issue through stages."""

from dataclasses import dataclass
import logging

from aiorchestra.agents import agent_family_from_config, build_agent_branch
from aiorchestra.config import load_config
from aiorchestra.stages.discover import discover_issues
from aiorchestra.stages.ci import wait_for_ci
from aiorchestra.stages.implement import implement
from aiorchestra.stages.prepare import prepare_environment
from aiorchestra.stages.publish import publish
from aiorchestra.stages.review import review
from aiorchestra.stages.types import IssueData, PipelineConfig, RemoteCheckFn
from aiorchestra.stages.validate import validate

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _IssueContext:
    repo: str
    branch: str
    issue: IssueData
    config: PipelineConfig
    repo_root: str

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
    ):
        self.repo = repo
        self.label = label
        self.issue_number = issue_number
        self.config = config
        self.config_path = config_path
        self.dry_run = dry_run
        self.workspace = workspace

    def run(self) -> int:
        """Run the full pipeline. Returns 0 on success, 1 on failure."""
        issues = discover_issues(
            self.repo,
            self.label,
            self.issue_number,
            agent_label=agent_family_from_config(self.config),
        )
        if not issues:
            log.info("No issues found.")
            return 0

        for issue in issues:
            log.info("Processing issue #%d: %s", issue["number"], issue["title"])
            if self.dry_run:
                log.info("[dry-run] Would process issue #%d", issue["number"])
                continue

            ok = self._process_issue(issue)
            if not ok:
                log.error("Failed to process issue #%d", issue["number"])
                return 1

        return 0

    def _process_issue(self, issue: IssueData) -> bool:
        ctx = self._prepare_issue(issue)
        if ctx is None:
            return False

        if not self._run_validation_loop(ctx):
            return False

        pr_url = publish(
            ctx.repo,
            ctx.branch,
            ctx.issue,
            repo_root=ctx.repo_root,
        )
        if not pr_url:
            return False

        pr_url = self._run_ci_fix_loop(ctx, pr_url)
        if not pr_url:
            return False

        pr_url = self._run_review_fix_loop(ctx, pr_url)
        if not pr_url:
            return False

        log.info("Issue #%d completed successfully.", issue["number"])
        return True

    def _prepare_issue(self, issue: IssueData) -> _IssueContext | None:
        branch = build_agent_branch(self.config, issue["number"])
        repo_root = prepare_environment(self.repo, branch, self.workspace)
        if not repo_root:
            return None

        log.info("Working in %s", repo_root)
        config = load_config(self.config_path, repo_root=repo_root)
        return _IssueContext(
            repo=self.repo,
            branch=branch,
            issue=issue,
            config=config,
            repo_root=repo_root,
        )

    def _run_validation_loop(
        self,
        ctx: _IssueContext,
        prompt_name: str = "implement",
        error_text: str | None = None,
        attempt_label: str = "Implementation",
    ) -> bool:
        validation_errors = error_text
        current_prompt = prompt_name

        for attempt in range(1, ctx.max_retries + 1):
            log.info("%s attempt %d/%d", attempt_label, attempt, ctx.max_retries)

            if not self._implement(
                ctx,
                prompt_name=current_prompt,
                error_text=validation_errors,
            ):
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
        )

    def _run_remote_fix_loop(
        self,
        ctx: _IssueContext,
        pr_url: str,
        stage_name: str,
        prompt_name: str,
        check_fn: RemoteCheckFn,
    ) -> str | None:
        for attempt in range(1, ctx.max_retries + 1):
            ok, feedback = check_fn(pr_url)
            if ok:
                return pr_url

            log.info("%s failed, attempt %d/%d", stage_name, attempt, ctx.max_retries)
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

        log.error("%s failed after %d attempts", stage_name, ctx.max_retries)
        return None

    def _implement(
        self,
        ctx: _IssueContext,
        prompt_name: str,
        error_text: str | None = None,
    ) -> bool:
        return implement(
            ctx.issue,
            ctx.config,
            prompt_name=prompt_name,
            error_text=error_text,
            repo_root=ctx.repo_root,
        )
