"""Aider CLI provider."""

from __future__ import annotations

from aiorchestra.ai._cli import CLIProvider


class AiderProvider(CLIProvider):
    """Invokes the ``aider`` CLI in scripting mode (``--message``).

    Aider differs from the other CLI agents in one important way: by default it
    *commits its own changes to git*.  AIOrchestra's pipeline owns committing
    (the ``publish`` stage stages and commits publishable changes, and enforces
    a "commits ahead of base" invariant), so we disable Aider's auto-commit by
    default and let it only edit the working tree — matching the contract of
    every other provider.  Set ``auto_commits: true`` to opt back into Aider's
    native git behaviour.

    ``--message`` sends a single prompt and exits (no interactive chat).
    ``--no-pretty``/``--no-stream`` give clean, parseable stdout, and
    ``--yes-always`` auto-confirms file additions and prompts.
    """

    _cli_name = "aider"

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["aider", "--no-pretty", "--no-stream"]

        if self._config.get("yes", True):
            cmd.append("--yes-always")

        if not self._config.get("auto_commits", False):
            cmd.extend(["--no-auto-commits", "--no-dirty-commits"])

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        cmd.extend(["--message", prompt])
        return cmd
