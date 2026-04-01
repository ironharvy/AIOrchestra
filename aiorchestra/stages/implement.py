"""Implementation stage — this is where AI tokens are spent."""

from __future__ import annotations

import logging

from aiorchestra.ai.claude import InvokeResult, invoke_claude
from aiorchestra.stages.types import IssueData, PipelineConfig
from aiorchestra.templates import render_template

log = logging.getLogger(__name__)


def _build_prompt(
    issue: IssueData,
    prompt_name: str = "implement",
    repo_root: str | None = None,
    error_text: str | None = None,
    osint_context: str = "",
) -> str:
    """Build a focused prompt for implementation or remediation."""
    # Format OSINT context as a clearly delimited section when present.
    osint_section = ""
    if osint_context:
        osint_section = (
            "\n## OSINT Intelligence\n\n"
            "The following reconnaissance data was gathered locally "
            "about targets referenced in this issue:\n\n"
            f"{osint_context}\n"
        )

    template_kwargs = {
        "repo_root": repo_root,
        "number": issue["number"],
        "title": issue["title"],
        "body": issue.get("body", ""),
        "osint_context": osint_section,
    }
    if error_text is not None:
        template_kwargs["errors"] = error_text

    return render_template(
        prompt_name,
        **template_kwargs,
    )


def implement(
    issue: IssueData,
    config: PipelineConfig,
    prompt_name: str = "implement",
    error_text: str | None = None,
    repo_root: str | None = None,
    osint_context: str = "",
) -> InvokeResult:
    """Invoke the AI to implement changes. Returns an ``InvokeResult``."""
    prompt = _build_prompt(issue, prompt_name, repo_root, error_text, osint_context)
    log.debug("Prompt: %s", prompt)
    ai_config = config.get("ai", {})
    provider = ai_config.get("provider", "claude-code")

    log.info("Invoking %s agent...", provider)
    if provider == "claude-code":
        return invoke_claude(prompt, ai_config, cwd=repo_root)

    log.error("Unknown AI provider: %s", provider)
    return InvokeResult(success=False)
