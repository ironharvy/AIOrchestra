"""Implementation stage — this is where AI tokens are spent."""

from __future__ import annotations

import logging

from aiorchestra.ai import InvokeResult, create_provider
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
    repo: str | None = None,
) -> InvokeResult:
    """Invoke the AI to implement changes. Returns an ``InvokeResult``."""
    prompt = _build_prompt(issue, prompt_name, repo_root, error_text, osint_context)
    log.debug("Prompt: %s", prompt)
    ai_config = dict(config.get("ai", {}))

    # Jules needs the GitHub owner/repo to create remote sessions.
    if repo and "repo" not in ai_config:
        ai_config["repo"] = repo

    provider = create_provider(ai_config)
    log.info("Invoking %s provider...", ai_config.get("provider", "claude-code"))
    return provider.run(prompt, cwd=repo_root)
