"""OpenAI Codex CLI provider."""

from __future__ import annotations

from aiorchestra.ai._cli import CLIProvider


class CodexProvider(CLIProvider):
    """Invokes the ``codex`` CLI in quiet (non-interactive) mode.

    Codex runs locally like Claude Code.  In ``full-auto`` approval mode it
    edits files without interactive confirmation (network is disabled by the
    CLI in this mode).
    """

    _cli_name = "codex"

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["codex", "--quiet"]

        approval = self._config.get("approval_mode", "full-auto")
        cmd.extend(["--approval-mode", approval])

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        cmd.append(prompt)
        return cmd
