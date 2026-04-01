"""Claude AI provider — wraps the Claude Code CLI."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Marker the agent emits when the task description is ambiguous.
_CLARIFICATION_RE = re.compile(
    r"^NEEDS_CLARIFICATION:\s*(.+)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class InvokeResult:
    """Structured outcome of an AI invocation."""

    success: bool
    output: str = ""
    needs_clarification: bool = False
    clarification_message: str = ""


def _parse_clarification(text: str) -> InvokeResult:
    """Check raw agent output for clarification requests."""
    match = _CLARIFICATION_RE.search(text)
    if match:
        return InvokeResult(
            success=True,
            output=text,
            needs_clarification=True,
            clarification_message=match.group(1).strip(),
        )
    return InvokeResult(success=True, output=text)


def invoke_claude(
    prompt: str,
    ai_config: dict,
    capture_output: bool = False,
    cwd: str | None = None,
) -> InvokeResult:
    """Invoke Claude Code CLI with the given prompt.

    Always returns an ``InvokeResult``.  When *capture_output* is True the
    full stdout is kept in ``result.output``; otherwise output is still
    available but primarily used for clarification detection.
    """
    provider = ai_config.get("provider", "claude-code")

    if provider == "claude-code":
        return _invoke_cli(prompt, ai_config, capture_output, cwd)

    log.error("Unknown AI provider: %s", provider)
    return InvokeResult(success=False)


def _invoke_cli(
    prompt: str, ai_config: dict, capture_output: bool, cwd: str | None = None
) -> InvokeResult:
    """Invoke claude-code CLI in non-interactive mode."""
    cmd = ["claude", "--print"]

    # Invariant 1: never invoke an agent that cannot write files.
    skip_perms = ai_config.get("skip_permissions", True)
    allowed_tools = ai_config.get("allowed_tools")

    if skip_perms:
        cmd.append("--dangerously-skip-permissions")

    if allowed_tools:
        for tool in allowed_tools:
            cmd.extend(["--allowedTools", tool])

    if not skip_perms and not allowed_tools:
        log.error(
            "AI agent has no file-editing permissions — refusing to invoke without tool access"
        )
        return InvokeResult(success=False)

    model = ai_config.get("model")
    if model:
        cmd.extend(["--model", model])

    log.info("Invoking Claude Code CLI...")
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        cwd=cwd,
    )

    if result.returncode != 0:
        log.error("Claude CLI failed: %s", result.stderr.strip())
        return InvokeResult(success=False, output=result.stderr)

    return _parse_clarification(result.stdout)
