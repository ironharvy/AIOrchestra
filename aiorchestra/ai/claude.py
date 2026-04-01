"""Claude AI provider — wraps the Claude Code CLI."""

import logging
import subprocess

log = logging.getLogger(__name__)


def invoke_claude(
    prompt: str,
    ai_config: dict,
    capture_output: bool = False,
    cwd: str | None = None,
) -> bool | str | None:
    """Invoke Claude Code CLI with the given prompt.

    If capture_output is False, returns True/False for success/failure.
    If capture_output is True, returns the output string or None on failure.
    """
    provider = ai_config.get("provider", "claude-code")

    if provider == "claude-code":
        return _invoke_cli(prompt, ai_config, capture_output, cwd)
    else:
        log.error("Unknown AI provider: %s", provider)
        return None if capture_output else False


def _invoke_cli(
    prompt: str, ai_config: dict, capture_output: bool, cwd: str | None = None
) -> bool | str | None:
    """Invoke claude-code CLI in non-interactive mode."""
    cmd = ["claude", "--print"]

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
        return None if capture_output else False

    if capture_output:
        return result.stdout
    return True
