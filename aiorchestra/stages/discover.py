"""Discover issues from GitHub by label. Pure shell — no AI tokens spent."""

import json
import logging
import time

from aiorchestra.agents import normalize_agent_family
from aiorchestra.stages._shell import run_command
from aiorchestra.stages.types import IssueData

log = logging.getLogger(__name__)
ISSUE_FIELDS = "number,title,body,labels,assignees"


def discover_issues(
    repo: str,
    label: str,
    issue_number: int | None = None,
    delay: int = 60,
    retries: int = 3,
    agent_label: str | None = None,
) -> list[IssueData]:
    """Fetch issues from GitHub using the gh CLI.

    Returns issue dicts enriched with normalized label and assignee names.
    """
    required_label = normalize_agent_family(agent_label or label)

    if issue_number:
        cmd = [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo,
            "--json",
            ISSUE_FIELDS,
        ]
    else:
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--label",
            label,
            "--state",
            "open",
            "--json",
            ISSUE_FIELDS,
            "--limit",
            "50",
        ]

    data = []
    for _ in range(retries):
        result = run_command(cmd, logger=log)
        log.debug("Result: %s", result.stdout)

        if result.returncode != 0:
            log.error("gh failed: %s", result.stderr.strip())
            return []

        data = json.loads(result.stdout)
        # gh issue view returns a single dict, list wraps it for consistency
        if isinstance(data, dict):
            data = [data]

        if data:
            break

        time.sleep(delay)

    if len(data) == 0:
        log.error("Failed to discover issues after %d attempts", retries)
        return []

    issues = [_normalize_issue(issue) for issue in data]
    eligible_issues = [
        issue for issue in issues if required_label in issue.get("labels", [])
    ]
    if not eligible_issues:
        log.error("No issues matched required agent label: %s", required_label)
        return []

    log.info("Found %d issue(s)", len(eligible_issues))
    return eligible_issues


def _normalize_issue(issue: dict) -> IssueData:
    """Convert GitHub CLI issue JSON into the shared IssueData shape."""
    normalized: IssueData = {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue.get("body", ""),
        "labels": _extract_names(issue.get("labels"), key="name"),
        "assignees": _extract_names(issue.get("assignees"), key="login"),
    }
    return normalized


def _extract_names(values: list[dict] | None, *, key: str) -> list[str]:
    """Normalize nested GitHub objects into lowercase string identifiers."""
    if not values:
        return []

    normalized = []
    for value in values:
        if isinstance(value, str):
            name = value
        else:
            name = value.get(key, "")

        if name:
            normalized.append(name.strip().lower())

    return normalized
