"""Goose CLI provider."""

from __future__ import annotations

from aiorchestra.ai._cli import CLIProvider


class GooseProvider(CLIProvider):
    """Invokes Block's ``goose`` CLI in headless ``goose run`` mode.

    ``goose run -t "<prompt>"`` executes a single instruction and exits.
    ``--no-session`` is passed by default so Goose doesn't persist session
    files into the workspace (which would otherwise show up as artifacts);
    set ``session: true`` to keep them.

    Goose has its own ``--provider`` flag selecting the LLM backend (openai,
    anthropic, ...), which collides with AIOrchestra's top-level ``provider``
    key used to pick *this* provider.  It is therefore configured via the
    distinct ``llm_provider`` key.  ``--model`` works as usual.  Both default
    to Goose's own configuration (``goose configure`` / ``GOOSE_*`` env vars)
    when unset.
    """

    _cli_name = "goose"

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["goose", "run"]

        if not self._config.get("session", False):
            cmd.append("--no-session")

        llm_provider = self._config.get("llm_provider")
        if llm_provider:
            cmd.extend(["--provider", llm_provider])

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        cmd.extend(["-t", prompt])
        return cmd
