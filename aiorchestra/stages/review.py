"""Review stage — AI reviews the diff. This is where AI tokens are spent."""

import logging

from aiorchestra.ai.claude import invoke_claude
from aiorchestra.stages._shell import run_command
from aiorchestra.stages.types import FeedbackResult, IssueData, PipelineConfig
from aiorchestra.templates import render_template

log = logging.getLogger(__name__)


def review(
    repo: str,
    branch: str,
    config: PipelineConfig,
    issue: IssueData | None = None,
    repo_root: str | None = None,
) -> FeedbackResult:
    """Run AI code review on the current diff. Returns (passed, feedback)."""
    result = run_command(["git", "diff", "origin/main...HEAD"], cwd=repo_root, logger=log)
    diff = result.stdout

    if not diff.strip():
        log.warning("No diff to review.")
        return True, None

    number = issue["number"] if issue else 0
    title = issue["title"] if issue else "unknown"

    prompt = render_template(
        "review",
        repo_root=repo_root,
        number=number,
        title=title,
        diff=diff,
    )

    review_config = config.get("review", {})
    ai_config = {**config.get("ai", {}), **review_config}

    result = invoke_claude(prompt, ai_config, capture_output=True, cwd=repo_root)

    if not result.success:
        return False, "Review invocation failed."

    if "LGTM" in result.output:
        log.info("Review passed.")
        return True, None

    log.info("Review flagged issues.")
    return False, result.output
