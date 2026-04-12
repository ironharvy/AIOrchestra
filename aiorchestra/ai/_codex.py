"""OpenAI Codex CLI provider."""

from __future__ import annotations

import logging

from aiorchestra.ai._cli import CLIProvider

log = logging.getLogger(__name__)

_SANDBOX_MODES = frozenset({"read-only", "workspace-write", "danger-full-access"})


class CodexProvider(CLIProvider):
    """Invokes the ``codex exec`` subcommand for non-interactive execution.

    ``codex exec`` replaces the former ``codex --quiet`` interface.
    In ``--full-auto`` mode the CLI uses *workspace-write* sandboxing and
    auto-approves tool calls (network is disabled by the CLI in this mode).
    """

    _cli_name = "codex"

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["codex", "exec"]

        approval = self._config.get("approval_mode", "full-auto")
        if approval == "full-auto":
            cmd.append("--full-auto")
        elif approval in _SANDBOX_MODES:
            cmd.extend(["--sandbox", approval])
        else:
            log.warning("Unknown approval_mode %r — omitting flag", approval)

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        cmd.append(prompt)
        return cmd
