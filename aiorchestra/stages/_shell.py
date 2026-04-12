"""Shared subprocess helpers for shell-backed stages."""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
import logging
import shlex
import subprocess
import time

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


def has_diff_from_main(repo_root: str) -> bool:
    """Return True if HEAD has changes (commits or file diffs) relative to origin/main."""
    result = run_command(
        ["git", "diff", "--stat", "origin/main...HEAD"],
        cwd=repo_root,
        logger=log,
    )
    return bool(result.stdout.strip())


class CommandError(RuntimeError):
    """Raised by :func:`run_command_or_fail` when a command exits non-zero."""

    def __init__(self, message: str, result: subprocess.CompletedProcess[str]) -> None:
        super().__init__(message)
        self.result = result


def run_command_or_fail(
    command: Command,
    *,
    error_msg: str,
    cwd: str | None = None,
    shell: bool | None = None,
    logger: logging.Logger | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and raise :class:`CommandError` on non-zero exit.

    This replaces the repeated pattern of::

        result = run_command(cmd, ...)
        if result.returncode != 0:
            log.error("...: %s", result.stderr.strip())
            return None

    Usage::

        result = run_command_or_fail(cmd, error_msg="git add failed", ...)
    """
    result = run_command(command, cwd=cwd, shell=shell, logger=logger)
    if result.returncode != 0:
        active_logger = logger or log
        detail = result.stderr.strip() or result.stdout.strip()
        active_logger.error("%s: %s", error_msg, detail)
        raise CommandError(f"{error_msg}: {detail}", result)
    return result


@dataclass
class Elapsed:
    """Mutable container for a timing measurement."""

    seconds: float = 0.0


@dataclass
class StageTimer:
    """Tracks per-step durations within a stage.

    Usage::

        timer = StageTimer()
        with timer.step("lint"):
            run_lint()
        with timer.step("test"):
            run_tests()
        log.info("[validate] %s", timer.summary())
    """

    _steps: dict[str, float] = field(default_factory=dict)
    _start: float = field(default_factory=time.monotonic)

    @contextmanager
    def step(self, name: str) -> Generator[Elapsed, None, None]:
        """Time a named step and record its duration."""
        elapsed = Elapsed()
        t0 = time.monotonic()
        try:
            yield elapsed
        finally:
            elapsed.seconds = time.monotonic() - t0
            self._steps[name] = elapsed.seconds

    @property
    def total(self) -> float:
        return time.monotonic() - self._start

    def summary(self) -> str:
        parts = [f"{k}: {v:.1f}s" for k, v in self._steps.items()]
        return ", ".join(parts)
