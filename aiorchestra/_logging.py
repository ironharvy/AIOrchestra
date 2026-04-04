"""Log formatters and setup for AIOrchestra."""

import json
import logging
import os
import sys
import time

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

# Third-party loggers to quiet at verbosity < 3
_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3")

# Verbosity level → root logging level
_VERBOSITY_TO_LEVEL = {
    0: logging.WARNING,
    1: logging.INFO,
    2: logging.DEBUG,
    3: logging.DEBUG,
}


class HumanFormatter(logging.Formatter):
    """Colored log formatter for TTY output."""

    def __init__(self, fmt: str, datefmt: str | None = None):
        super().__init__(fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        level_color = _LEVEL_COLORS.get(record.levelno, "")
        levelname_colored = f"{level_color}{record.levelname}{_RESET}"
        name_colored = f"{_NAME_COLOR}{record.name}{_RESET}"
        asctime_colored = f"{_TIME_COLOR}{self.formatTime(record, self.datefmt)}{_RESET}"
        msg_colored = f"{level_color}{record.getMessage()}{_RESET}"
        return f"{asctime_colored} [{levelname_colored}] {name_colored}: {msg_colored}"


# Keep the old name for any imports that reference it directly
ColorFormatter = HumanFormatter


class JSONFormatter(logging.Formatter):
    """Machine-readable JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("issue", "stage", "agent", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _resolve_level(verbosity: int) -> int:
    """Return logging level from verbosity count, honoring LOG_LEVEL env var."""
    env_level = os.environ.get("LOG_LEVEL", "").upper()
    if env_level:
        numeric = getattr(logging, env_level, None)
        if isinstance(numeric, int):
            return numeric
    return _VERBOSITY_TO_LEVEL.get(verbosity, logging.DEBUG)


def _use_json(stream: object) -> bool:
    """Return True when JSON format should be used."""
    env_fmt = os.environ.get("LOG_FORMAT", "").lower()
    if env_fmt == "json":
        return True
    if env_fmt == "text":
        return False
    # Auto-detect: use JSON when not a TTY (CI, pipes)
    return not (hasattr(stream, "isatty") and stream.isatty())


def setup_logging(verbosity: int = 0, *, verbose: bool = False) -> None:
    """Configure root logger.

    Args:
        verbosity: Number of -v flags (0=WARNING, 1=INFO, 2=DEBUG, 3=firehose).
        verbose:   Legacy boolean flag — maps to verbosity=1 when True.
    """
    if verbose and verbosity == 0:
        verbosity = 1

    level = _resolve_level(verbosity)
    datefmt = "%H:%M:%S"
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(level)

    if _use_json(sys.stderr):
        stderr_handler.setFormatter(JSONFormatter())
    else:
        stderr_handler.setFormatter(HumanFormatter(fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stderr_handler)

    # Optional file handler — always JSON
    log_file = os.environ.get("LOG_FILE", "")
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(JSONFormatter())
        root.addHandler(file_handler)

    # Suppress noisy third-party loggers unless firehose (-vvv)
    if verbosity < 3:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
