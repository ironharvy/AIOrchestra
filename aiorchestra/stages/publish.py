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
    committed = _commit_changes(issue, repo_root)
    if committed is None:
        return None

    # Invariant 3: never push a branch with zero commits ahead of the base.
    # Invariant 4: never create a PR with an empty diff.
    if not _has_commits_ahead(repo_root):
        log.error("Nothing to publish — branch has no changes relative to main")
        return None

    if not _push_branch(branch, repo_root):
        return None

    if pr_url:
        log.info("Updated branch pushed for PR: %s", pr_url)
        return pr_url

    return _create_pr(repo, branch, issue, repo_root)


def _has_commits_ahead(repo_root: str) -> bool:
    """Return True if HEAD has commits that origin/main does not."""
    result = run_command(
        ["git", "log", "origin/main..HEAD", "--oneline"],
        cwd=repo_root,
        logger=log,
    )
    return bool(result.stdout.strip())


def _commit_changes(issue: IssueData, repo_root: str) -> bool | None:
    """Commit any local changes before pushing.

    Returns True if changes were committed, False if there was nothing to
    commit, or None on a git error (caller should abort).
    """
    result = run_command(["git", "status", "--porcelain"], cwd=repo_root, logger=log)
    if result.returncode != 0:
        log.error("Failed to inspect git status: %s", result.stderr.strip())
        return None

    if not result.stdout.strip():
        log.debug("No local changes to commit.")
        return False

    log.info("Committing local changes for issue #%d", issue["number"])
    result = run_command(["git", "add", "-A"], cwd=repo_root, logger=log)
    if result.returncode != 0:
        log.error("git add failed: %s", result.stderr.strip())
        return None

    result = run_command(
        ["git", "commit", "-m", f"Fix #{issue['number']}: {issue['title']}"],
        cwd=repo_root,
        logger=log,
    )
    if result.returncode != 0:
        log.error("git commit failed: %s", result.stderr.strip())
        return None

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

    log.info("Checking for existing PR for branch %s", branch)
    existing = run_command(
        ["gh", "pr", "view", "--repo", repo, branch, "--json", "url", "--jq", ".url"],
        cwd=repo_root,
        logger=log,
    )
    if existing.returncode == 0 and existing.stdout.strip():
        pr_url = existing.stdout.strip()
        log.info("PR already exists: %s", pr_url)
        return pr_url

    log.info("Creating PR for issue #%d", issue["number"])
    result = run_command(
        ["gh", "pr", "create", "--repo", repo, "--head", branch, "--title", title, "--body", body],
        cwd=repo_root,
        logger=log,
    )
    if result.returncode != 0:
        log.error("PR creation failed: %s", result.stderr.strip())
        return None

    pr_url = result.stdout.strip()
    log.info("PR created: %s", pr_url)
    return pr_url
