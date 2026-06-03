"""Tests for the Antigravity CLI provider."""

import subprocess

from aiorchestra.ai import AntigravityProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "antigravity", **overrides}
    return AntigravityProvider(config)


def test_antigravity_basic_invocation(monkeypatch):
    """Antigravity is invoked with -p and skips permissions by default."""
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
    assert captured["cmd"][:2] == ["agy", "-p"]
    assert "--dangerously-skip-permissions" in captured["cmd"]
    assert "fix the bug" in captured["cmd"]
    assert captured["cwd"] == "/tmp/repo"


def test_antigravity_skip_permissions_disabled(monkeypatch):
    """skip_permissions=False omits the --dangerously-skip-permissions flag."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(skip_permissions=False)
    provider.run("hello")

    assert "--dangerously-skip-permissions" not in captured["cmd"]


def test_antigravity_custom_model(monkeypatch):
    """Model flag is forwarded via -m when configured."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(model="gemini-3-pro")
    provider.run("hello")

    assert "-m" in captured["cmd"]
    idx = captured["cmd"].index("-m")
    assert captured["cmd"][idx + 1] == "gemini-3-pro"


def test_antigravity_failure(monkeypatch):
    """Non-zero exit code results in failure."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="agy error")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("hello")

    assert not result.success


def test_antigravity_via_registry():
    """The registry resolves the antigravity provider id."""
    provider = create_provider({"provider": "antigravity"})
    assert isinstance(provider, AntigravityProvider)
