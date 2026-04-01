"""Colored log formatter using ANSI escape codes."""

import logging

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",    # cyan
    logging.INFO: "\033[32m",     # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",    # red
    logging.CRITICAL: "\033[31m" + _BOLD,  # bold red
}


class ColoredFormatter(logging.Formatter):
    """Formatter that adds ANSI color codes to log level names."""

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        original_levelname = record.levelname
        record.levelname = f"{color}{record.levelname}{_RESET}"
        result = super().format(record)
        record.levelname = original_levelname
        return result


def setup_logging(*, verbose: bool = False) -> None:
    """Configure root logger with colored output."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        ColoredFormatter(
            fmt=f"{_DIM}%(asctime)s{_RESET} [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logging.root.setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
