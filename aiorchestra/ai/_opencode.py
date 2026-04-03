"""OpenCode CLI provider."""

from __future__ import annotations

from aiorchestra.ai._cli import CLIProvider


class OpenCodeProvider(CLIProvider):
    """Invokes the ``opencode`` CLI in non-interactive mode.

    OpenCode is a terminal-based AI coding agent.  Passing a prompt directly
    to ``opencode run`` runs it non-interactively, writing the result to
    stdout.  ``--yes`` auto-approves tool use without interactive confirmation.
    """

    _cli_name = "opencode"

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["opencode", "run"]

        if self._config.get("yes", True):
            cmd.append("--yes")

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        cmd.extend(["--", prompt])
        return cmd
