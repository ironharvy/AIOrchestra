"""CLI provider base — shared subprocess boilerplate for CLI-backed agents.

Most AI backends (Claude Code, Codex, Gemini, OpenCode) follow the same
pattern: build a command list, run it as a subprocess, check the return code,
and parse clarification markers from stdout.  :class:`CLIProvider` captures
that shared logic so concrete subclasses only need to define how to build
their command.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from abc import abstractmethod

from aiorchestra.ai._base import AIProvider, InvokeResult, _parse_clarification

log = logging.getLogger(__name__)


class CLIProvider(AIProvider):
    """Base for providers that wrap a local CLI tool."""

    @abstractmethod
    def _build_command(self, prompt: str) -> list[str]:
        """Return the full command list to execute."""

    @property
    def _prompt_via_stdin(self) -> bool:
        """If True, prompt is passed via stdin instead of as an argument."""
        return False

    @property
    @abstractmethod
    def _cli_name(self) -> str:
        """Binary name for logging and availability checks."""

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        cwd: str | None = None,
    ) -> InvokeResult:
        cmd = self._build_command(prompt)

        kwargs: dict = {"capture_output": True, "text": True, "cwd": cwd}
        if self._prompt_via_stdin:
            kwargs["input"] = prompt

        log.info("Invoking %s CLI...", self._cli_name)
        result = subprocess.run(cmd, **kwargs)

        if result.returncode != 0:
            log.error("%s CLI failed: %s", self._cli_name, result.stderr.strip())
            return InvokeResult(success=False, output=result.stderr)

        return _parse_clarification(result.stdout)

    def available(self) -> bool:
        return shutil.which(self._cli_name) is not None
