"""Review stage — AI reviews the diff. This is where AI tokens are spent."""

import logging
import subprocess

from aiorchestra.ai.claude import invoke_claude
from aiorchestra.templates import render_template

log = logging.getLogger(__name__)


def review(
    repo: str, branch: str, config: dict, issue: dict | None = None,
    repo_root: str | None = None,
) -> tuple[bool, str | None]:
    """Run AI code review on the current diff. Returns (passed, feedback)."""
    result = subprocess.run(
        ["git", "diff", "origin/main...HEAD"],
        capture_output=True, text=True,
    )
    diff = result.stdout

    if not diff.strip():
        log.warning("No diff to review.")
        return True, None

    number = issue["number"] if issue else 0
    title = issue["title"] if issue else "unknown"

    prompt = render_template(
        "review", repo_root=repo_root, number=number, title=title, diff=diff,
    )

    review_config = config.get("review", {})
    ai_config = {**config.get("ai", {}), **review_config}

    output = invoke_claude(prompt, ai_config, capture_output=True)

    if output is None:
        return False, "Review invocation failed."

    if "LGTM" in output:
        log.info("Review passed.")
        return True, None

    log.info("Review flagged issues.")
    return False, output
