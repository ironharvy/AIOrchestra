"""Review stage — AI reviews the diff. This is where AI tokens are spent."""

import logging
import subprocess

from aiorchestra.ai.claude import invoke_claude

log = logging.getLogger(__name__)


def review(repo: str, branch: str, config: dict) -> tuple[bool, str | None]:
    """Run AI code review on the current diff. Returns (passed, feedback)."""
    # Get the diff (deterministic)
    result = subprocess.run(
        ["git", "diff", "origin/main...HEAD"],
        capture_output=True, text=True,
    )
    diff = result.stdout

    if not diff.strip():
        log.warning("No diff to review.")
        return True, None

    prompt = (
        "Review the following code diff. Focus on:\n"
        "- Bugs or logic errors\n"
        "- Security issues\n"
        "- Missing edge cases\n\n"
        "If the code looks good, respond with exactly: LGTM\n"
        "If there are issues, describe them clearly.\n\n"
        f"```diff\n{diff}\n```"
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
