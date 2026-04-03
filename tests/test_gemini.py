"""Tests for the Google Gemini CLI provider."""

import subprocess

from aiorchestra.ai import GeminiProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "gemini", **overrides}
    return GeminiProvider(config)


def test_gemini_basic_invocation(monkeypatch):
    """Gemini is invoked with -p and --yolo by default."""
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
    assert captured["cmd"][:2] == ["gemini", "-p"]
    assert "--yolo" in captured["cmd"]
    assert "fix the bug" in captured["cmd"]
    assert captured["cwd"] == "/tmp/repo"


def test_gemini_yolo_disabled(monkeypatch):
    """yolo=False omits --yolo flag."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(yolo=False)
    provider.run("hello")

    assert "--yolo" not in captured["cmd"]


def test_gemini_custom_model(monkeypatch):
    """Model flag is forwarded when configured."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(model="gemini-2.5-flash")
    provider.run("hello")

    assert "-m" in captured["cmd"]
    idx = captured["cmd"].index("-m")
    assert captured["cmd"][idx + 1] == "gemini-2.5-flash"


def test_gemini_failure(monkeypatch):
    """Non-zero exit code results in failure."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="gemini error")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("hello")

    assert not result.success
    assert "gemini error" in result.output


def test_gemini_clarification(monkeypatch):
    """Clarification marker is detected in gemini output."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="NEEDS_CLARIFICATION: What framework?", stderr=""
        )

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("hello")

    assert result.success
    assert result.needs_clarification
    assert result.clarification_message == "What framework?"


def test_gemini_available(monkeypatch):
    """available() checks for gemini on PATH."""
    monkeypatch.setattr(
        "aiorchestra.ai._cli.shutil.which",
        lambda name: "/usr/bin/gemini" if name == "gemini" else None,
    )
    assert _make_provider().available()

    monkeypatch.setattr("aiorchestra.ai._cli.shutil.which", lambda name: None)
    assert not _make_provider().available()


def test_create_provider_gemini():
    """Factory creates GeminiProvider for provider='gemini'."""
    provider = create_provider({"provider": "gemini"})
    assert isinstance(provider, GeminiProvider)
