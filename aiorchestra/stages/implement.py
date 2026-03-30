"""Implementation stage — this is where AI tokens are spent."""

import logging

from aiorchestra.ai.claude import invoke_claude

log = logging.getLogger(__name__)


def _build_prompt(issue: dict, previous_errors: str | None = None) -> str:
    """Build a focused prompt from the issue and optional error context."""
    parts = [
        f"Implement the following GitHub issue.\n",
        f"Issue #{issue['number']}: {issue['title']}\n",
        f"{issue.get('body', '')}\n",
        "Do NOT run tests — just implement the changes.",
    ]
    if previous_errors:
        parts.append(f"\nPrevious attempt failed with these errors:\n{previous_errors}")
        parts.append("\nFix these errors in your implementation.")
    return "\n".join(parts)


def implement(issue: dict, config: dict, previous_errors: str | None = None) -> bool:
    """Invoke the AI to implement changes. Returns True on success."""
    prompt = _build_prompt(issue, previous_errors)
    ai_config = config.get("ai", {})
    return invoke_claude(prompt, ai_config)
