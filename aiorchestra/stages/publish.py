"""Publish stage — push branch and create PR. Pure shell — no AI tokens spent."""

import logging
import time
from pathlib import Path

from aiorchestra.stages._shell import (
    CommandError,
    has_diff_from_main,
    run_command,
    run_command_or_fail,
)
from aiorchestra.stages._workspace_artifacts import (
    GitStatusError,
    ensure_local_git_excludes,
    stage_publishable_changes,
)
from aiorchestra.stages.types import IssueData, PublishResult

log = logging.getLogger(__name__)

_MAX_DIFF_STAT_LINES = 20
_MAX_PR_BODY_CHARS = 60_000
_PR_CREATE_ATTEMPTS = 2
_PR_CREATE_RETRY_DELAY_SECONDS = 2.0
_NON_RETRYABLE_PR_ERRORS = ("body is too long",)
_TRANSIENT_PR_ERROR_PATTERNS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "temporary failure",
    "connection reset",
    "connection refused",
    "connection aborted",
    "network is unreachable",
    "no such host",
    "unexpected eof",
    "tls handshake timeout",
    "internal server error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "http 502",
    "http 503",
    "http 504",
)


def publish(
    repo: str,
    branch: str,
    issue: IssueData,
    repo_root: str,
    pr_url: str | None = None,
) -> PublishResult:
    """Commit local changes, push the branch, and ensure a PR exists."""
    committed = _commit_changes(issue, repo_root)
    if committed is None:
        return None

    # Invariant 3: never push a branch with zero commits ahead of the base.
    # Invariant 4: never create a PR with an empty diff.
    if not has_diff_from_main(repo_root):
        log.error("Nothing to publish — branch has no changes relative to main")
        return None

    if not _push_branch(branch, repo_root):
        return None

    if pr_url:
        log.info("Updated branch pushed for PR: %s", pr_url)
        return pr_url

    return _create_pr(repo, branch, issue, repo_root)


def _commit_changes(issue: IssueData, repo_root: str) -> bool | None:
    """Commit any local changes before pushing.

    Returns True if changes were committed, False if there was nothing to
    commit, or None on a git error (caller should abort).
    """
    try:
        ensure_local_git_excludes(Path(repo_root))
        staged_paths = stage_publishable_changes(repo_root)
    except GitStatusError as exc:
        log.error("%s", exc)
        return None

    if not staged_paths:
        log.debug("No publishable local changes to commit.")
        return False

    log.info("Committing local changes for issue #%d", issue["number"])
    try:
        run_command_or_fail(
            [
                "git",
                "commit",
                "-m",
                f"Fix #{issue['number']}: {issue['title']}",
                "--",
                *staged_paths,
            ],
            error_msg="git commit failed",
            cwd=repo_root,
            logger=log,
        )
    except CommandError:
        return None

    return True


def _push_branch(branch: str, repo_root: str) -> bool:
    """Push the current branch to origin."""
    log.info("Pushing branch %s", branch)
    try:
        run_command_or_fail(
            ["git", "push", "-u", "origin", branch],
            error_msg="Push failed",
            cwd=repo_root,
            logger=log,
        )
    except CommandError:
        return False
    return True


def _find_existing_pr(repo: str, branch: str, repo_root: str) -> str | None:
    """Return the URL of an open PR for *branch*, or ``None`` if none exists."""
    result = run_command(
        ["gh", "pr", "view", "--repo", repo, "--head", branch, "--json", "url", "--jq", ".url"],
        cwd=repo_root,
        logger=log,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def _summarize_diff_stat(diff_output: str) -> str:
    """Cap diff-stat output line count for the PR body (no path masking)."""
    lines = [line for line in diff_output.strip().splitlines() if line.strip()]
    if not lines:
        return ""

    summary_line = ""
    if "|" not in lines[-1]:
        summary_line = lines.pop()

    if len(lines) > _MAX_DIFF_STAT_LINES:
        original = len(lines)
        omitted = original - _MAX_DIFF_STAT_LINES
        lines = lines[:_MAX_DIFF_STAT_LINES]
        note = f"[Diff stat truncated to first {_MAX_DIFF_STAT_LINES} lines; omitted {omitted}.]"
        log.info("Truncated diff stat from %d to %d file lines", original, _MAX_DIFF_STAT_LINES)
    else:
        note = ""

    rendered_lines = list(lines)
    if summary_line:
        rendered_lines.append(summary_line)
    if note:
        rendered_lines.append(note)
    return "\n".join(rendered_lines).strip()


def _enforce_pr_body_cap(body: str, closing_line: str) -> str:
    """Keep the final body below GitHub's body-length limit."""
    if len(body) <= _MAX_PR_BODY_CHARS:
        return body

    marker = f"[PR body truncated to {_MAX_PR_BODY_CHARS} characters.]"
    reserved = len(closing_line) + len(marker) + 4
    head_budget = max(0, _MAX_PR_BODY_CHARS - reserved)
    truncated_head = body[:head_budget].rstrip()
    log.warning("Truncated final PR body from %d to %d characters", len(body), _MAX_PR_BODY_CHARS)
    return f"{truncated_head}\n\n{marker}\n\n{closing_line}"


def _is_transient_pr_error(detail: str) -> bool:
    """Return True when a gh/GitHub failure looks retryable."""
    lowered = detail.lower()
    if any(pattern in lowered for pattern in _NON_RETRYABLE_PR_ERRORS):
        return False
    return any(pattern in lowered for pattern in _TRANSIENT_PR_ERROR_PATTERNS)


def _build_pr_body(issue: IssueData, repo_root: str, repo: str) -> str:
    """Build a PR body: link to the issue, diff summary, labels (no full issue text)."""
    number = issue["number"]
    sections: list[str] = []
    closing_line = f"Closes #{number}"

    # Summary
    sections.append(f"Automated implementation for #{number}.")

    # Full requirements live on the issue page; do not paste the issue body here.
    issue_url = f"https://github.com/{repo}/issues/{number}"
    sections.append(f"**Issue:** {issue_url}")

    # Changed files summary via git diff --stat (zero AI cost).
    diff_stat = run_command(
        ["git", "diff", "--stat", "origin/main...HEAD"],
        cwd=repo_root,
        logger=log,
    )
    if diff_stat.returncode == 0 and diff_stat.stdout.strip():
        summarized_diff = _summarize_diff_stat(diff_stat.stdout)
        if summarized_diff:
            sections.append(f"## Changes\n\n```\n{summarized_diff}\n```")

    # Labels carried over from the issue.
    labels = issue.get("labels", [])
    if labels:
        badge_list = ", ".join(f"`{lbl}`" for lbl in labels)
        sections.append(f"**Labels:** {badge_list}")

    # Closing reference must come last so GitHub links the PR to the issue.
    sections.append(closing_line)

    return _enforce_pr_body_cap("\n\n".join(sections), closing_line)


def _create_pr(repo: str, branch: str, issue: IssueData, repo_root: str) -> PublishResult:
    """Create a PR for the pushed branch, or return the existing one."""
    existing = _find_existing_pr(repo, branch, repo_root)
    if existing:
        log.info("PR already exists for branch %s: %s", branch, existing)
        return existing

    title = f"Fix #{issue['number']}: {issue['title']}"
    body = _build_pr_body(issue, repo_root, repo)

    log.info("Creating PR for issue #%d", issue["number"])
    for attempt in range(1, _PR_CREATE_ATTEMPTS + 1):
        try:
            result = run_command_or_fail(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    repo,
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body",
                    body,
                ],
                error_msg="PR creation failed",
                cwd=repo_root,
                logger=log,
            )
            pr_url = result.stdout.strip()
            log.info("PR created: %s", pr_url)
            return pr_url
        except CommandError as exc:
            detail = exc.result.stderr.strip() or exc.result.stdout.strip() or str(exc)
            if attempt >= _PR_CREATE_ATTEMPTS or not _is_transient_pr_error(detail):
                return None

            existing = _find_existing_pr(repo, branch, repo_root)
            if existing:
                log.info("PR appeared after transient create failure: %s", existing)
                return existing

            log.warning(
                "Transient PR creation failure on attempt %d/%d, retrying: %s",
                attempt,
                _PR_CREATE_ATTEMPTS,
                detail,
            )
            time.sleep(_PR_CREATE_RETRY_DELAY_SECONDS)

    return None
