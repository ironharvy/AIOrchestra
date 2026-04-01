"""Publish stage — push branch and create PR. Pure shell — no AI tokens spent."""

import logging

from aiorchestra.stages._shell import run_command
from aiorchestra.stages.types import IssueData, PublishResult

log = logging.getLogger(__name__)


def publish(
    repo: str,
    branch: str,
    issue: IssueData,
    repo_root: str,
    pr_url: str | None = None,
) -> PublishResult:
    """Commit local changes, push the branch, and ensure a PR exists."""
    if not _commit_changes(issue, repo_root):
        return None

    if not _push_branch(branch, repo_root):
        return None

    if pr_url:
        log.info("Updated branch pushed for PR: %s", pr_url)
        return pr_url

    return _create_pr(repo, branch, issue, repo_root)


def _commit_changes(issue: IssueData, repo_root: str) -> bool:
    """Commit any local changes before pushing."""
    result = run_command(["git", "status", "--porcelain"], cwd=repo_root, logger=log)
    if result.returncode != 0:
        log.error("Failed to inspect git status: %s", result.stderr.strip())
        return False

    if not result.stdout.strip():
        log.info("No local changes to commit.")
        return True

    log.info("Committing local changes for issue #%d", issue["number"])
    result = run_command(["git", "add", "-A"], cwd=repo_root, logger=log)
    if result.returncode != 0:
        log.error("git add failed: %s", result.stderr.strip())
        return False

    result = run_command(
        ["git", "commit", "-m", f"Fix #{issue['number']}: {issue['title']}"],
        cwd=repo_root,
        logger=log,
    )
    if result.returncode != 0:
        log.error("git commit failed: %s", result.stderr.strip())
        return False

    return True


def _push_branch(branch: str, repo_root: str) -> bool:
    """Push the current branch to origin."""
    log.info("Pushing branch %s", branch)
    result = run_command(["git", "push", "-u", "origin", branch], cwd=repo_root, logger=log)
    if result.returncode != 0:
        log.error("Push failed: %s", result.stderr.strip())
        return False

    return True


def _create_pr(repo: str, branch: str, issue: IssueData, repo_root: str) -> PublishResult:
    """Create a PR for the pushed branch."""
    title = f"Fix #{issue['number']}: {issue['title']}"
    body = f"Automated implementation for #{issue['number']}.\n\nCloses #{issue['number']}"

    log.info("Creating PR for issue #%d", issue["number"])
    result = run_command(
        ["gh", "pr", "create", "--repo", repo, "--head", branch,
         "--title", title, "--body", body],
        cwd=repo_root,
        logger=log,
    )
    if result.returncode != 0:
        log.error("PR creation failed: %s", result.stderr.strip())
        return None

    pr_url = result.stdout.strip()
    log.info("PR created: %s", pr_url)
    return pr_url
