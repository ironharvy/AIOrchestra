"""Discover issues from GitHub by label. Pure shell — no AI tokens spent."""

import json
import logging
import subprocess

log = logging.getLogger(__name__)


def discover_issues(
    repo: str, label: str, issue_number: int | None = None
) -> list[dict]:
    """Fetch issues from GitHub using the gh CLI.

    Returns a list of dicts with keys: number, title, body.
    """
    if issue_number:
        cmd = ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json",
               "number,title,body"]
    else:
        cmd = ["gh", "issue", "list", "--repo", repo, "--label", label,
               "--state", "open", "--json", "number,title,body", "--limit", "50"]

    log.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        log.error("gh failed: %s", result.stderr.strip())
        return []

    data = json.loads(result.stdout)
    # gh issue view returns a single dict, list wraps it for consistency
    if isinstance(data, dict):
        data = [data]

    log.info("Found %d issue(s)", len(data))
    return data
