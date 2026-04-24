"""Discover issues from GitHub by label. Pure shell — no AI tokens spent."""

from collections import defaultdict
import json
import logging
import time

from aiorchestra.ai import normalize_agent_family
from aiorchestra.stages._shell import run_command
from aiorchestra.stages.labels import SKIP_LABELS
from aiorchestra.stages.types import IssueData

log = logging.getLogger(__name__)
ISSUE_FIELDS = "number,title,body,labels,assignees,comments"
SEARCH_FIELDS = "number,title,body,labels,assignees,repository"
DISPATCH_LABEL = "aiorchestra"


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
            DISPATCH_LABEL,
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
    eligible_issues = [issue for issue in issues if required_label in issue.get("labels", [])]
    if not eligible_issues:
        log.error("No issues matched required agent label: %s", required_label)
        return []

    # Filter out issues that are already in progress or waiting on a human.
    ready_issues = [
        issue for issue in eligible_issues if not SKIP_LABELS.intersection(issue.get("labels", []))
    ]
    skipped = len(eligible_issues) - len(ready_issues)
    if skipped:
        log.info(
            "Skipping %d issue(s) (in-progress or pending clarification)",
            skipped,
        )
    if not ready_issues:
        log.info("All matching issues are in-progress or waiting for clarification")
        return []

    log.info("Found %d issue(s)", len(ready_issues))
    return ready_issues


def _normalize_issue(issue: dict) -> IssueData:
    """Convert GitHub CLI issue JSON into the shared IssueData shape."""
    normalized: IssueData = {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue.get("body", ""),
        "labels": _extract_names(issue.get("labels"), key="name"),
        "assignees": _extract_names(issue.get("assignees"), key="login"),
    }
    comments = issue.get("comments")
    if comments:
        normalized["comments"] = _normalize_comments(comments)
    return normalized


def _normalize_comments(comments: list[dict]) -> list[dict[str, str]]:
    """Extract author + body from gh CLI comment objects."""
    result = []
    for c in comments:
        author = c.get("author", {})
        login = author.get("login", "unknown") if isinstance(author, dict) else str(author)
        body = c.get("body", "")
        if body:
            result.append({"author": login, "body": body})
    return result


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


def discover_all_issues(
    owner: str = "@me",
    label: str = DISPATCH_LABEL,
    limit: int = 100,
) -> dict[str, list[IssueData]]:
    """Search for labeled issues across all repos owned by *owner*.

    Returns a dict mapping ``owner/repo`` to its matching issues.
    """
    cmd = [
        "gh",
        "search",
        "issues",
        "--owner",
        owner,
        "--label",
        label,
        "--state",
        "open",
        "--json",
        SEARCH_FIELDS,
        "--limit",
        str(limit),
    ]

    result = run_command(cmd, logger=log)
    if result.returncode != 0:
        log.error("gh search failed: %s", result.stderr.strip())
        return {}

    data = json.loads(result.stdout)
    if not data:
        log.info("No issues found across repos for owner=%s label=%s", owner, label)
        return {}

    grouped: dict[str, list[IssueData]] = defaultdict(list)
    for raw in data:
        repo_info = raw.get("repository", {})
        repo = repo_info.get("nameWithOwner", "")
        if not repo:
            continue
        issue = _normalize_issue(raw)
        if SKIP_LABELS.intersection(issue.get("labels", [])):
            continue
        grouped[repo].append(issue)

    log.info(
        "Found %d issue(s) across %d repo(s)",
        sum(len(v) for v in grouped.values()),
        len(grouped),
    )
    return dict(grouped)
