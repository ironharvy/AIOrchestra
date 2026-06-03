"""Tests for the Cursor CLI provider."""

import subprocess

from aiorchestra.ai import CursorProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "cursor", **overrides}
    return CursorProvider(config)


def test_cursor_basic_invocation(monkeypatch):
    """Cursor is invoked with -p and --force by default."""
    captured = {}

    def fake_run(cmd, *, capture_output=False, text=False, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout="done\n", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("fix the bug", cwd="/tmp/repo")

    assert result.success
    assert result.output == "done\n"
    assert captured["cmd"][:2] == ["cursor-agent", "-p"]
    assert "--force" in captured["cmd"]
    assert "fix the bug" in captured["cmd"]
    assert captured["cwd"] == "/tmp/repo"


def test_cursor_force_disabled(monkeypatch):
    """force=False omits the --force flag."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(force=False)
    provider.run("hello")

    assert "--force" not in captured["cmd"]


def test_cursor_custom_model(monkeypatch):
    """Model flag is forwarded when configured."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(model="claude-4-sonnet")
    provider.run("hello")

    assert "--model" in captured["cmd"]
    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "claude-4-sonnet"


def test_cursor_failure(monkeypatch):
    """Non-zero exit code results in failure."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="cursor error")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("hello")

    assert not result.success


def test_cursor_via_registry():
    """The registry resolves the cursor provider id."""
    provider = create_provider({"provider": "cursor"})
    assert isinstance(provider, CursorProvider)
