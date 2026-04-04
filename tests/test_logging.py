"""Tests for multi-level verbose logging."""

import json
import logging
import os
import sys
from io import StringIO
from unittest import mock

from aiorchestra._logging import (
    HumanFormatter,
    JSONFormatter,
    _resolve_level,
    _use_json,
    setup_logging,
)


# ---------------------------------------------------------------------------
# _resolve_level
# ---------------------------------------------------------------------------


def test_resolve_level_no_verbose():
    assert _resolve_level(0) == logging.WARNING


def test_resolve_level_v():
    assert _resolve_level(1) == logging.INFO


def test_resolve_level_vv():
    assert _resolve_level(2) == logging.DEBUG


def test_resolve_level_vvv():
    assert _resolve_level(3) == logging.DEBUG


def test_resolve_level_env_override(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert _resolve_level(3) == logging.ERROR


def test_resolve_level_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "NOTAREAL")
    assert _resolve_level(1) == logging.INFO


# ---------------------------------------------------------------------------
# _use_json
# ---------------------------------------------------------------------------


def test_use_json_env_json(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    assert _use_json(sys.stderr) is True


def test_use_json_env_text(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "text")
    assert _use_json(sys.stderr) is False


def test_use_json_non_tty(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    stream = StringIO()  # StringIO has no isatty
    assert _use_json(stream) is True


def test_use_json_tty(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    tty = mock.MagicMock()
    tty.isatty.return_value = True
    assert _use_json(tty) is False


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------


def test_json_formatter_basic():
    fmt = JSONFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello world",
        args=(),
        exc_info=None,
    )
    out = json.loads(fmt.format(record))
    assert out["msg"] == "hello world"
    assert out["level"] == "INFO"
    assert out["logger"] == "test.logger"
    assert "ts" in out


def test_json_formatter_extra_fields():
    fmt = JSONFormatter()
    record = logging.LogRecord(
        name="aiorchestra.pipeline",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="stage done",
        args=(),
        exc_info=None,
    )
    record.issue = 42
    record.stage = "implement"
    out = json.loads(fmt.format(record))
    assert out["issue"] == 42
    assert out["stage"] == "implement"


# ---------------------------------------------------------------------------
# HumanFormatter
# ---------------------------------------------------------------------------


def test_human_formatter_contains_message():
    fmt = HumanFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
    record = logging.LogRecord(
        name="aiorchestra",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=(),
        exc_info=None,
    )
    out = fmt.format(record)
    assert "test message" in out
    assert "aiorchestra" in out


# ---------------------------------------------------------------------------
# setup_logging integration
# ---------------------------------------------------------------------------


def _fresh_root():
    """Return root logger with all handlers removed."""
    root = logging.getLogger()
    root.handlers.clear()
    return root


def test_setup_logging_verbosity_0(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)
    root = _fresh_root()
    setup_logging(verbosity=0)
    assert root.level == logging.WARNING
    root.handlers.clear()


def test_setup_logging_verbosity_1(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)
    root = _fresh_root()
    setup_logging(verbosity=1)
    assert root.level == logging.INFO
    root.handlers.clear()


def test_setup_logging_verbosity_2(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)
    root = _fresh_root()
    setup_logging(verbosity=2)
    assert root.level == logging.DEBUG
    root.handlers.clear()


def test_setup_logging_legacy_verbose(monkeypatch):
    """verbose=True should behave like verbosity=1."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)
    root = _fresh_root()
    setup_logging(verbose=True)
    assert root.level == logging.INFO
    root.handlers.clear()


def test_setup_logging_noisy_loggers_suppressed(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)
    root = _fresh_root()
    setup_logging(verbosity=2)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("urllib3").level == logging.WARNING
    root.handlers.clear()


def test_setup_logging_firehose_allows_noisy(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)
    root = _fresh_root()
    # Reset noisy loggers first
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    setup_logging(verbosity=3)
    # At firehose, noisy loggers should NOT be set to WARNING
    assert logging.getLogger("httpx").level != logging.WARNING
    root.handlers.clear()


def test_setup_logging_file_handler(monkeypatch, tmp_path):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    log_path = str(tmp_path / "aiorchestra.log")
    monkeypatch.setenv("LOG_FILE", log_path)
    root = _fresh_root()
    setup_logging(verbosity=1)
    # Emit a record and flush
    logger = logging.getLogger("aiorchestra.test")
    logger.info("file test message")
    for h in root.handlers:
        h.flush()
    root.handlers.clear()

    assert os.path.exists(log_path)
    lines = open(log_path).readlines()
    assert lines, "log file should not be empty"
    entry = json.loads(lines[-1])
    assert entry["msg"] == "file test message"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_verbose_count():
    """Ensure -v/-vv/-vvv map to the correct verbosity counts."""
    from aiorchestra.cli import build_parser

    parser = build_parser()

    args = parser.parse_args(["run", "--repo", "owner/repo"])
    assert args.verbose == 0

    args = parser.parse_args(["run", "--repo", "owner/repo", "-v"])
    assert args.verbose == 1

    args = parser.parse_args(["run", "--repo", "owner/repo", "-vv"])
    assert args.verbose == 2

    args = parser.parse_args(["run", "--repo", "owner/repo", "-vvv"])
    assert args.verbose == 3
