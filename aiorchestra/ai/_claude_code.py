"""Claude Code CLI provider."""

from __future__ import annotations

import logging

from aiorchestra.ai._base import InvokeResult
from aiorchestra.ai._cli import CLIProvider

log = logging.getLogger(__name__)


class ClaudeCodeProvider(CLIProvider):
    """Invokes the ``claude`` CLI in non-interactive (``--print``) mode."""

    _cli_name = "claude"

    @property
    def _prompt_via_stdin(self) -> bool:
        return True

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        cwd: str | None = None,
    ) -> InvokeResult:
        skip_perms = self._config.get("skip_permissions", True)
        allowed_tools = self._config.get("allowed_tools")

        if not skip_perms and not allowed_tools:
            log.error(
                "AI agent has no file-editing permissions — refusing to invoke without tool access"
            )
            return InvokeResult(success=False)

        return super().run(prompt, system=system, cwd=cwd)

    def _build_command(self, prompt: str) -> list[str]:
        cmd: list[str] = ["claude", "--print"]

        if self._config.get("skip_permissions", True):
            cmd.append("--dangerously-skip-permissions")

        allowed_tools = self._config.get("allowed_tools")
        if allowed_tools:
            for tool in allowed_tools:
                cmd.extend(["--allowedTools", tool])

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        return cmd
