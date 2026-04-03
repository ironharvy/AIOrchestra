"""Tests for the OpenCode CLI provider."""

import subprocess

from aiorchestra.ai.provider import OpenCodeProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "opencode", **overrides}
    return OpenCodeProvider(config)


def test_opencode_basic_invocation(monkeypatch):
    """OpenCode is invoked with 'run' and --yes by default."""
    captured = {}

    def fake_run(cmd, *, capture_output=False, text=False, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout="done\n", stderr="")

    monkeypatch.setattr("aiorchestra.ai.provider.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("fix the bug", cwd="/tmp/repo")

    assert result.success
    assert result.output == "done\n"
    assert captured["cmd"][:2] == ["opencode", "run"]
    assert "--yes" in captured["cmd"]
    assert "fix the bug" in captured["cmd"]
    assert captured["cwd"] == "/tmp/repo"


def test_opencode_yes_disabled(monkeypatch):
    """yes=False omits --yes flag."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai.provider.subprocess.run", fake_run)

    provider = _make_provider(yes=False)
    provider.run("hello")

    assert "--yes" not in captured["cmd"]


def test_opencode_custom_model(monkeypatch):
    """Model flag is forwarded when configured."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai.provider.subprocess.run", fake_run)

    provider = _make_provider(model="gpt-4o")
    provider.run("hello")

    assert "--model" in captured["cmd"]
    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "gpt-4o"


def test_opencode_failure(monkeypatch):
    """Non-zero exit code results in failure."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="opencode error")

    monkeypatch.setattr("aiorchestra.ai.provider.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("hello")

    assert not result.success
    assert "opencode error" in result.output


def test_opencode_clarification(monkeypatch):
    """Clarification marker is detected in opencode output."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="NEEDS_CLARIFICATION: Which database?", stderr=""
        )

    monkeypatch.setattr("aiorchestra.ai.provider.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("hello")

    assert result.success
    assert result.needs_clarification
    assert result.clarification_message == "Which database?"


def test_opencode_available(monkeypatch):
    """available() checks for opencode on PATH."""
    monkeypatch.setattr(
        "aiorchestra.ai.provider.shutil.which",
        lambda name: "/usr/local/bin/opencode" if name == "opencode" else None,
    )
    assert _make_provider().available()

    monkeypatch.setattr("aiorchestra.ai.provider.shutil.which", lambda name: None)
    assert not _make_provider().available()


def test_create_provider_opencode():
    """Factory creates OpenCodeProvider for provider='opencode'."""
    provider = create_provider({"provider": "opencode"})
    assert isinstance(provider, OpenCodeProvider)
