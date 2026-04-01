"""Shared subprocess helpers for shell-backed stages."""

from collections.abc import Sequence
import logging
import shlex
import subprocess

log = logging.getLogger(__name__)

Command = str | Sequence[str]


def _display_command(command: Command) -> str:
    if isinstance(command, str):
        return command

    return shlex.join(command)


def run_command(
    command: Command,
    *,
    cwd: str | None = None,
    check: bool = False,
    shell: bool | None = None,
    logger: logging.Logger | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command with consistent logging and text output capture."""
    if shell is None:
        shell = isinstance(command, str)

    active_logger = logger or log
    active_logger.info("Running: %s", _display_command(command))
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=check,
        cwd=cwd,
        shell=shell,
    )
