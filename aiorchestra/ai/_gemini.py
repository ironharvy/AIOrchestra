"""Google Gemini CLI provider."""

from __future__ import annotations

from aiorchestra.ai._cli import CLIProvider


class GeminiProvider(CLIProvider):
    """Invokes the ``gemini`` CLI in headless (``-p``) mode.

    Gemini CLI is Google's local coding agent — the same category as Claude
    Code and Codex.  The ``-p`` flag runs it non-interactively, returning
    text output to stdout.  ``--yolo`` auto-approves tool use (equivalent
    to ``--dangerously-skip-permissions`` for Claude).
    """

    _cli_name = "gemini"

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["gemini", "-p"]

        if self._config.get("yolo", True):
            cmd.append("--yolo")

        model = self._config.get("model")
        if model:
            cmd.extend(["-m", model])

        cmd.append(prompt)
        return cmd
