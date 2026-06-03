"""Google Antigravity CLI provider."""

from __future__ import annotations

from aiorchestra.ai._cli import CLIProvider


class AntigravityProvider(CLIProvider):
    """Invokes the ``agy`` (Antigravity) CLI in headless (``-p``) mode.

    Antigravity CLI is Google's successor to Gemini CLI.  The ``-p`` flag runs
    a single prompt non-interactively, emitting the response to stdout.
    ``--dangerously-skip-permissions`` auto-approves tool use (the analogue of
    Gemini CLI's ``--yolo``).  Authentication is via ``GEMINI_API_KEY`` /
    ``ANTIGRAVITY_API_KEY`` or stored OAuth credentials — same as the binary's
    own expectations, so no extra handling is needed here.
    """

    _cli_name = "agy"

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["agy", "-p"]

        if self._config.get("skip_permissions", True):
            cmd.append("--dangerously-skip-permissions")

        model = self._config.get("model")
        if model:
            cmd.extend(["-m", model])

        cmd.append(prompt)
        return cmd
