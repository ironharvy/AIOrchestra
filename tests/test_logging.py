"""Tests for multi-level verbose logging and observability log messages."""

from __future__ import annotations

import json
import logging
import os
import sys
import types
from io import StringIO
from unittest import mock

from aiorchestra._logging import (
    HumanFormatter,
    JSONFormatter,
    _resolve_level,
    _use_json,
    setup_logging,
)
from aiorchestra.ai import InvokeResult
from aiorchestra.stages import review as rev_mod


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


def test_setup_logging_clears_existing_handlers(monkeypatch):
    """Calling setup_logging() twice should not duplicate handlers."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)
    root = _fresh_root()
    setup_logging(verbosity=1)
    first_count = len(root.handlers)
    setup_logging(verbosity=1)
    assert len(root.handlers) == first_count
    root.handlers.clear()


def test_setup_logging_invalid_log_file(monkeypatch):
    """An invalid LOG_FILE path should not raise an exception."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setenv("LOG_FILE", "/nonexistent/dir/impossible.log")
    root = _fresh_root()
    setup_logging(verbosity=1)  # should not raise
    # Only the stderr handler should be present (file handler failed gracefully)
    assert len(root.handlers) == 1
    root.handlers.clear()


def test_json_formatter_subsecond_precision():
    """JSONFormatter timestamps should include sub-second precision."""
    fmt = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="precision test",
        args=(),
        exc_info=None,
    )
    out = json.loads(fmt.format(record))
    # ISO 8601 with sub-second precision contains a dot
    assert "." in out["ts"]


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


# ===========================================================================
# Observability — verifying key log messages are emitted
# ===========================================================================

ISSUE = {"number": 42, "title": "Add feature X"}
DIFF = "+def foo():\n+    return 42\n"
LONG_FEEDBACK = "Issue: " + ("x" * 600)


class FakeProvider:
    def __init__(self, output="LGTM", success=True, is_available=True):
        self._output = output
        self._success = success
        self._is_available = is_available

    def run(self, prompt, *, system=None, cwd=None):
        return InvokeResult(success=self._success, output=self._output)

    def available(self):
        return self._is_available


def _patch_review_provider(monkeypatch, output="LGTM", success=True, is_available=True):
    provider = FakeProvider(output=output, success=success, is_available=is_available)
    monkeypatch.setattr(rev_mod, "create_provider", lambda cfg: provider)
    monkeypatch.setattr(rev_mod, "render_template", lambda name, **kw: "prompt")
    return provider


# ---------------------------------------------------------------------------
# review.py — T3 review feedback logging
# ---------------------------------------------------------------------------


def test_ai_review_logs_feedback_at_info_truncated(monkeypatch, caplog):
    _patch_review_provider(monkeypatch, output=LONG_FEEDBACK)

    with caplog.at_level(logging.INFO, logger="aiorchestra.stages.review"):
        from aiorchestra.stages.review import _run_ai_review

        ok, feedback = _run_ai_review(DIFF, {}, {}, ISSUE, None)

    assert not ok
    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("flagged issues" in m for m in info_msgs)
    # At INFO level the message should be truncated (<=500 chars of the feedback)
    matching = [m for m in info_msgs if "flagged issues" in m]
    assert matching
    assert len(matching[0]) < len(LONG_FEEDBACK) + 100  # truncation applied


def test_ai_review_logs_full_feedback_at_debug(monkeypatch, caplog):
    _patch_review_provider(monkeypatch, output=LONG_FEEDBACK)

    with caplog.at_level(logging.DEBUG, logger="aiorchestra.stages.review"):
        from aiorchestra.stages.review import _run_ai_review

        _run_ai_review(DIFF, {}, {}, ISSUE, None)

    debug_msgs = [r.message for r in caplog.records if r.levelname == "DEBUG"]
    assert any("full feedback" in m for m in debug_msgs)
    full_msg = next(m for m in debug_msgs if "full feedback" in m)
    assert LONG_FEEDBACK in full_msg


# ---------------------------------------------------------------------------
# review.py — T4 cross-model feedback logging
# ---------------------------------------------------------------------------


def test_cross_model_review_logs_provider_and_model(monkeypatch, caplog):
    _patch_review_provider(monkeypatch, output="LGTM")
    tier_cfg = {"provider": "ollama", "ollama": {"model": "phi3", "endpoint": "http://h:1234"}}

    with caplog.at_level(logging.INFO, logger="aiorchestra.stages.review"):
        from aiorchestra.stages.review import _run_cross_model_review

        _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)

    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("ollama" in m for m in info_msgs)


def test_cross_model_review_logs_feedback_when_flagged(monkeypatch, caplog):
    _patch_review_provider(monkeypatch, output=LONG_FEEDBACK)
    tier_cfg = {"provider": "ollama", "ollama": {}}

    with caplog.at_level(logging.INFO, logger="aiorchestra.stages.review"):
        from aiorchestra.stages.review import _run_cross_model_review

        ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)

    assert not ok
    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("flagged issues" in m for m in info_msgs)


# ---------------------------------------------------------------------------
# _cli.py — provider + model logged on invocation
# ---------------------------------------------------------------------------


def test_cli_provider_logs_model(monkeypatch, caplog):
    import subprocess

    from aiorchestra.ai._claude_code import ClaudeCodeProvider

    def fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout="LGTM", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    provider = ClaudeCodeProvider({"model": "sonnet", "skip_permissions": True})
    with caplog.at_level(logging.INFO, logger="aiorchestra.ai._cli"):
        provider.run("test prompt")

    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("sonnet" in m for m in info_msgs)


def test_cli_provider_logs_default_when_no_model(monkeypatch, caplog):
    import subprocess

    from aiorchestra.ai._claude_code import ClaudeCodeProvider

    def fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout="LGTM", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    provider = ClaudeCodeProvider({"skip_permissions": True})
    with caplog.at_level(logging.INFO, logger="aiorchestra.ai._cli"):
        provider.run("test prompt")

    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("default" in m for m in info_msgs)


# ---------------------------------------------------------------------------
# implement.py — provider + model + prompt_name logged
# ---------------------------------------------------------------------------


def test_implement_logs_provider_and_model(monkeypatch, caplog):
    from aiorchestra.stages import implement as impl_mod

    monkeypatch.setattr(impl_mod, "render_template", lambda name, **kw: "prompt text")
    monkeypatch.setattr(
        impl_mod,
        "create_provider",
        lambda cfg: FakeProvider(output="done"),
    )

    issue = {"number": 1, "title": "Test", "body": "", "comments": []}
    config = {"ai": {"provider": "claude-code", "model": "opus"}}

    with caplog.at_level(logging.INFO, logger="aiorchestra.stages.implement"):
        from aiorchestra.stages.implement import implement

        implement(issue, config, prompt_name="implement")

    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("claude-code" in m for m in info_msgs)
    assert any("opus" in m for m in info_msgs)
    assert any("implement" in m for m in info_msgs)


# ---------------------------------------------------------------------------
# pipeline.py — remediation feedback logged
# ---------------------------------------------------------------------------


def test_pipeline_logs_feedback_on_remediation(monkeypatch, caplog, tmp_path):
    from aiorchestra.pipeline import Pipeline

    feedback_text = "Review: missing error handling in handler.py"

    review_calls = [0]

    def fake_check(repo, branch, config, *, issue=None, repo_root=None):
        review_calls[0] += 1
        if review_calls[0] == 1:
            return False, feedback_text
        return True, None

    monkeypatch.setattr("aiorchestra.pipeline.prepare_environment", lambda r, b, w: str(tmp_path))
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {"ai": {"max_retries": 2}, "ci": {"enabled": False}},
    )
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, cfg: "")
    monkeypatch.setattr("aiorchestra.pipeline._has_changes", lambda r: True)
    monkeypatch.setattr("aiorchestra.pipeline._branch_has_existing_work", lambda r: False)
    monkeypatch.setattr("aiorchestra.pipeline.validate", lambda cfg, repo_root=None: (True, None))
    monkeypatch.setattr(
        "aiorchestra.pipeline.implement",
        lambda issue, cfg, prompt_name="implement", error_text=None, repo_root=None, osint_context="", repo=None: (
            InvokeResult(success=True)
        ),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.publish",
        lambda repo, branch, issue, repo_root, pr_url=None: "https://example.test/pr/1",
    )
    monkeypatch.setattr("aiorchestra.pipeline.review", fake_check)
    monkeypatch.setattr("aiorchestra.pipeline.add_label", lambda r, n, lbl: True)
    monkeypatch.setattr("aiorchestra.pipeline.remove_label", lambda r, n, lbl: True)
    monkeypatch.setattr("aiorchestra.pipeline.swap_label", lambda r, n, rm, add: True)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        parallel=False,
    )

    with caplog.at_level(logging.INFO, logger="aiorchestra.pipeline"):
        pipeline.run(issues=[{"number": 1, "title": "Test"}])

    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("missing error handling" in m for m in info_msgs)


# ---------------------------------------------------------------------------
# ci.py — CI failure output logged
# ---------------------------------------------------------------------------


def test_ci_logs_failure_output_at_info(monkeypatch, caplog):
    from aiorchestra.stages import ci as ci_mod

    failure_lines = ["line " + str(i) for i in range(30)]
    failure_output = "\n".join(failure_lines)
    job_link = "https://github.com/owner/repo/actions/runs/123/job/456"

    call_count = [0]

    def fake_run(cmd, logger=None):
        call_count[0] += 1
        if "run" in cmd and "view" in cmd:
            # gh run view <url> --log-failed
            return types.SimpleNamespace(returncode=0, stdout=failure_output, stderr="")
        # gh pr checks (both polling and log-fetch)
        checks = [{"name": "test", "bucket": "fail", "state": "FAILURE", "link": job_link}]
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(checks), stderr="")

    monkeypatch.setattr(ci_mod, "run_command", fake_run)

    with caplog.at_level(logging.INFO, logger="aiorchestra.stages.ci"):
        from aiorchestra.stages.ci import wait_for_ci

        ok, output = wait_for_ci("https://pr/1", {"ci": {"timeout": 1, "poll_interval": 0}})

    assert not ok
    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("first 20 lines" in m for m in info_msgs)
    # Only first 20 lines should appear at INFO
    matching = next(m for m in info_msgs if "first 20 lines" in m)
    assert "line 19" in matching
    assert "line 20" not in matching


def test_ci_logs_full_output_at_debug(monkeypatch, caplog):
    from aiorchestra.stages import ci as ci_mod

    failure_lines = ["line " + str(i) for i in range(30)]
    failure_output = "\n".join(failure_lines)
    job_link = "https://github.com/owner/repo/actions/runs/123/job/456"

    def fake_run(cmd, logger=None):
        if "run" in cmd and "view" in cmd:
            return types.SimpleNamespace(returncode=0, stdout=failure_output, stderr="")
        checks = [{"name": "test", "bucket": "fail", "state": "FAILURE", "link": job_link}]
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(checks), stderr="")

    monkeypatch.setattr(ci_mod, "run_command", fake_run)

    with caplog.at_level(logging.DEBUG, logger="aiorchestra.stages.ci"):
        from aiorchestra.stages.ci import wait_for_ci

        wait_for_ci("https://pr/1", {"ci": {"timeout": 1, "poll_interval": 0}})

    debug_msgs = [r.message for r in caplog.records if r.levelname == "DEBUG"]
    assert any("full output" in m for m in debug_msgs)
    full_msg = next(m for m in debug_msgs if "full output" in m)
    assert "line 29" in full_msg


# ---------------------------------------------------------------------------
# clarification.py — clarification message logged
# ---------------------------------------------------------------------------


def test_clarification_logs_message(monkeypatch, caplog):
    from aiorchestra.stages import clarification as clar_mod
    from aiorchestra.stages import labels as labels_mod

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(clar_mod, "run_command", fake_run)
    monkeypatch.setattr(labels_mod, "run_command", fake_run)

    from aiorchestra.stages.clarification import request_clarification

    with caplog.at_level(logging.INFO, logger="aiorchestra.stages.clarification"):
        request_clarification(
            "owner/repo",
            {"number": 7, "title": "Ambiguous"},
            "Which database adapter?",
        )

    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any("Which database adapter?" in m for m in info_msgs)
