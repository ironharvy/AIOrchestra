"""Tests for the Claude Code CLI provider."""

import subprocess

from aiorchestra.ai import ClaudeCodeProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "claude-code", **overrides}
    return ClaudeCodeProvider(config)


def _fake_run_capture(captured):
    def fake_run(cmd, *, capture_output=False, text=False, cwd=None, input=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["input"] = input
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    return fake_run


def test_claude_basic_invocation(monkeypatch):
    """Claude is invoked via ``--print`` with stdin-fed prompt."""
    captured = {}
    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", _fake_run_capture(captured))

    provider = _make_provider()
    result = provider.run("fix the bug", cwd="/tmp/repo")

    assert result.success
    assert captured["cmd"][:2] == ["claude", "--print"]
    assert "--dangerously-skip-permissions" in captured["cmd"]
    assert captured["input"] == "fix the bug"
    assert captured["cwd"] == "/tmp/repo"


def test_claude_effort_flag(monkeypatch):
    """``effort`` config maps to ``--effort <level>``."""
    captured = {}
    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", _fake_run_capture(captured))

    _make_provider(effort="high").run("hello")

    assert "--effort" in captured["cmd"]
    idx = captured["cmd"].index("--effort")
    assert captured["cmd"][idx + 1] == "high"


def test_claude_no_effort_flag_when_unset(monkeypatch):
    """Without ``effort`` configured the flag is omitted."""
    captured = {}
    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", _fake_run_capture(captured))

    _make_provider().run("hello")

    assert "--effort" not in captured["cmd"]


def test_claude_custom_model(monkeypatch):
    """Model flag is forwarded when configured."""
    captured = {}
    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", _fake_run_capture(captured))

    _make_provider(model="claude-opus-4-7").run("hello")

    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "claude-opus-4-7"


def test_create_provider_claude_code():
    """Factory creates ClaudeCodeProvider for provider='claude-code'."""
    provider = create_provider({"provider": "claude-code"})
    assert isinstance(provider, ClaudeCodeProvider)
