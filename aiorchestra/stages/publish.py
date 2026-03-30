"""Publish stage — push branch and create PR. Pure shell — no AI tokens spent."""

import logging
import subprocess

log = logging.getLogger(__name__)


def publish(repo: str, branch: str, issue: dict) -> str | None:
    """Push the branch and create a PR. Returns the PR URL or None on failure."""
    # Push
    log.info("Pushing branch %s", branch)
    result = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log.error("Push failed: %s", result.stderr.strip())
        return None

    # Create PR
    title = f"Fix #{issue['number']}: {issue['title']}"
    body = f"Automated implementation for #{issue['number']}.\n\nCloses #{issue['number']}"

    log.info("Creating PR for issue #%d", issue["number"])
    result = subprocess.run(
        ["gh", "pr", "create", "--repo", repo, "--head", branch,
         "--title", title, "--body", body],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log.error("PR creation failed: %s", result.stderr.strip())
        return None

    pr_url = result.stdout.strip()
    log.info("PR created: %s", pr_url)
    return pr_url
