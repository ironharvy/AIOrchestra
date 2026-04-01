"""Colored log formatter for terminal output."""

import logging
import sys

_RESET = "\033[0m"

_LEVEL_COLORS = {
    logging.DEBUG: "\033[2m",  # dim
    logging.INFO: "\033[36m",  # cyan
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}

_NAME_COLOR = "\033[2;37m"  # dim white
_TIME_COLOR = "\033[2;34m"  # dim blue


class ColorFormatter(logging.Formatter):
    """Log formatter that applies ANSI colors per level."""

    def __init__(self, fmt: str, datefmt: str | None = None):
        super().__init__(fmt, datefmt=datefmt)
        self._plain = logging.Formatter(fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        level_color = _LEVEL_COLORS.get(record.levelno, "")

        record.levelname_colored = f"{level_color}{record.levelname}{_RESET}"
        record.name_colored = f"{_NAME_COLOR}{record.name}{_RESET}"
        record.asctime_colored = f"{_TIME_COLOR}{self.formatTime(record, self.datefmt)}{_RESET}"
        record.msg_colored = f"{level_color}{record.getMessage()}{_RESET}"

        return (
            f"{record.asctime_colored} "
            f"[{record.levelname_colored}] "
            f"{record.name_colored}: "
            f"{record.msg_colored}"
        )


def setup_logging(verbose: bool = False) -> None:
    """Configure root logger with colored output if on a TTY."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
        handler.setFormatter(ColorFormatter(fmt, datefmt=datefmt))
    else:
        handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
