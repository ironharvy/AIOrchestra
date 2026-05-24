"""Cursor CLI provider."""

from __future__ import annotations

from aiorchestra.ai._cli import CLIProvider


class CursorProvider(CLIProvider):
    """Invokes the ``cursor-agent`` CLI in print (``-p``) mode.

    Cursor CLI is Anysphere's terminal coding agent.  The ``-p`` flag runs a
    single prompt non-interactively, writing the result to stdout.  In print
    mode file edits are only *proposed* unless ``--force`` is passed, so
    ``force`` defaults to True here to mirror the auto-approve behaviour of the
    other CLI providers.
    """

    _cli_name = "cursor-agent"

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["cursor-agent", "-p"]

        if self._config.get("force", True):
            cmd.append("--force")

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        cmd.append(prompt)
        return cmd
