"""OpenCode CLI provider."""

from __future__ import annotations

import subprocess

from aiorchestra.ai._base import InvokeResult, _parse_clarification
from aiorchestra.ai._cli import CLIProvider


class OpenCodeProvider(CLIProvider):
    """Invokes the ``opencode`` CLI in non-interactive mode.

    OpenCode is a terminal-based AI coding agent.  Passing a prompt directly
    to ``opencode run`` runs it non-interactively, writing the result to
    stdout.  ``--dangerously-skip-permissions`` auto-approves tool use
    without interactive confirmation.  ``--dir`` is required because OpenCode
    ignores the subprocess cwd.
    """

    _cli_name = "opencode"

    def _build_command(self, prompt: str, *, cwd: str | None = None) -> list[str]:
        cmd: list[str] = ["opencode", "run"]

        if self._config.get("dangerously-skip-permissions", True):
            cmd.append("--dangerously-skip-permissions")

        model = self._config.get("model") or "openai/gpt-5.4"
        if model == "default":
            model = "openai/gpt-5.4"
        if model:
            cmd.extend(["--model", model])

        if cwd:
            cmd.extend(["--dir", cwd])

        cmd.extend(["--", prompt])
        return cmd

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        cwd: str | None = None,
    ) -> InvokeResult:
        cmd = self._build_command(prompt, cwd=cwd)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return InvokeResult(success=False, output=result.stderr)
        return _parse_clarification(result.stdout)
