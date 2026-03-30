"""Implementation stage — this is where AI tokens are spent."""

import logging

from aiorchestra.ai.claude import invoke_claude
from aiorchestra.templates import render_template

log = logging.getLogger(__name__)


def _build_prompt(
    issue: dict, repo_root: str | None = None, previous_errors: str | None = None
) -> str:
    """Build a focused prompt from the issue and optional error context."""
    if previous_errors:
        return render_template(
            "fix_validation",
            repo_root=repo_root,
            number=issue["number"],
            title=issue["title"],
            body=issue.get("body", ""),
            errors=previous_errors,
        )
    return render_template(
        "implement",
        repo_root=repo_root,
        number=issue["number"],
        title=issue["title"],
        body=issue.get("body", ""),
    )


def implement(
    issue: dict,
    config: dict,
    previous_errors: str | None = None,
    repo_root: str | None = None,
) -> bool:
    """Invoke the AI to implement changes. Returns True on success."""
    prompt = _build_prompt(issue, repo_root, previous_errors)
    ai_config = config.get("ai", {})
    return invoke_claude(prompt, ai_config)
