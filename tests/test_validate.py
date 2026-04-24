"""Tests for the validate stage including T1 static analysis."""

import types

from aiorchestra.stages import validate as val_mod
from aiorchestra.stages.validate import (
    _has_python_sources,
    _run_static_analysis,
    validate,
)


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


# ---------------------------------------------------------------------------
# Python-source detection and skip-when-non-python behaviour
# ---------------------------------------------------------------------------


def test_has_python_sources_detects_py_files(tmp_path):
    (tmp_path / "module.py").write_text("print('hi')\n")
    assert _has_python_sources(str(tmp_path)) is True


def test_has_python_sources_ignores_py_in_venv(tmp_path):
    """A stray `.venv/` from _setup_venv must not make a static repo look
    like a Python project."""
    (tmp_path / "index.html").write_text("<html></html>\n")
    venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    venv.mkdir(parents=True)
    (venv / "pygments.py").write_text("pass\n")
    assert _has_python_sources(str(tmp_path)) is False


def test_has_python_sources_none_is_permissive():
    """Legacy callers that pass repo_root=None should not be silenced."""
    assert _has_python_sources(None) is True


def test_validate_skips_python_tools_for_non_python_repo(monkeypatch, tmp_path):
    """ruff/pytest/bandit must be skipped when the repo has no Python files."""
    (tmp_path / "index.html").write_text("<html></html>\n")
    (tmp_path / "styles.css").write_text("body { }\n")

    invoked = []

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        invoked.append(cmd_str)
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
                    "commands": [
                        "bandit -r .",
                        "semgrep --config=auto --quiet .",
                    ],
                }
            ]
        },
    }

    ok, errors = validate(config, repo_root=str(tmp_path))

    assert ok
    assert errors is None
    # Neither ruff, pytest, nor bandit should have been invoked.
    assert not any("ruff" in c for c in invoked)
    assert not any(c.startswith("pytest") for c in invoked)
    assert not any("bandit" in c for c in invoked)
    # semgrep is language-agnostic, so it still runs.
    assert any("semgrep" in c for c in invoked)


def test_validate_treats_pytest_no_tests_collected_as_pass(monkeypatch, tmp_path):
    """pytest exit code 5 (no tests collected) must not trip validation."""
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n")

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        if cmd_str.startswith("pytest"):
            return types.SimpleNamespace(
                returncode=5, stdout="no tests ran", stderr=""
            )
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(val_mod, "run_command", fake_run)
    monkeypatch.setattr(val_mod.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    ok, errors = validate(
        {"test": {"command": "pytest", "lint_command": "ruff check ."}},
        repo_root=str(tmp_path),
    )

    assert ok
    assert errors is None
