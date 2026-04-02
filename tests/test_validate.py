"""Tests for the validate stage including T1 static analysis."""

import types

from aiorchestra.stages import validate as val_mod
from aiorchestra.stages.validate import _run_static_analysis, validate


def test_validate_passes_when_lint_and_tests_succeed(monkeypatch):
    calls = []

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        calls.append(cmd if isinstance(cmd, str) else " ".join(cmd))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(val_mod, "run_command", fake_run)

    ok, errors = validate({"test": {"command": "pytest", "lint_command": "ruff check ."}})
    assert ok
    assert errors is None
    assert calls == ["ruff check .", "pytest"]


def test_validate_collects_lint_and_test_errors(monkeypatch):
    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        return types.SimpleNamespace(returncode=1, stdout="bad", stderr="err")

    monkeypatch.setattr(val_mod, "run_command", fake_run)

    ok, errors = validate({"test": {}})
    assert not ok
    assert "Lint errors" in errors
    assert "Test errors" in errors


def test_static_analysis_runs_when_enabled(monkeypatch):
    calls = []

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        calls.append(cmd if isinstance(cmd, str) else " ".join(cmd))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(val_mod, "run_command", fake_run)
    monkeypatch.setattr(val_mod.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    review_cfg = {
        "tiers": [
            {
                "name": "static-analysis",
                "enabled": True,
                "commands": ["semgrep --config=auto .", "bandit -r . -q"],
            }
        ]
    }

    errors = _run_static_analysis(review_cfg)
    assert errors == []
    assert calls == ["semgrep --config=auto .", "bandit -r . -q"]


def test_static_analysis_skips_missing_tools(monkeypatch):
    calls = []

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        calls.append(cmd if isinstance(cmd, str) else " ".join(cmd))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(val_mod, "run_command", fake_run)
    monkeypatch.setattr(val_mod.shutil, "which", lambda tool: None)

    review_cfg = {
        "tiers": [
            {
                "name": "static-analysis",
                "enabled": True,
                "commands": ["semgrep --config=auto ."],
            }
        ]
    }

    errors = _run_static_analysis(review_cfg)
    assert errors == []
    assert calls == []


def test_static_analysis_skipped_when_disabled(monkeypatch):
    review_cfg = {
        "tiers": [{"name": "static-analysis", "enabled": False, "commands": ["semgrep ."]}]
    }

    errors = _run_static_analysis(review_cfg)
    assert errors == []


def test_static_analysis_reports_failures(monkeypatch):
    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        return types.SimpleNamespace(returncode=1, stdout="vuln found", stderr="")

    monkeypatch.setattr(val_mod, "run_command", fake_run)
    monkeypatch.setattr(val_mod.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    review_cfg = {
        "tiers": [
            {
                "name": "static-analysis",
                "enabled": True,
                "commands": ["bandit -r ."],
            }
        ]
    }

    errors = _run_static_analysis(review_cfg)
    assert len(errors) == 1
    assert "bandit" in errors[0]
    assert "vuln found" in errors[0]


def test_validate_includes_static_analysis_errors(monkeypatch):
    """Static analysis errors from T1 are included in validate output."""
    call_count = {"run": 0}

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        call_count["run"] += 1
        # Lint and tests pass, but static analysis fails
        if "bandit" in cmd_str:
            return types.SimpleNamespace(returncode=1, stdout="B101 assert used", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(val_mod, "run_command", fake_run)
    monkeypatch.setattr(val_mod.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    config = {
        "test": {"command": "pytest", "lint_command": "ruff check ."},
        "review": {
            "tiers": [
                {
                    "name": "static-analysis",
                    "enabled": True,
                    "commands": ["bandit -r ."],
                }
            ]
        },
    }

    ok, errors = validate(config)
    assert not ok
    assert "bandit" in errors
    assert "B101" in errors
