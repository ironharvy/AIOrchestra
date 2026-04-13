"""Tests for the OpenAI Codex CLI provider."""

import subprocess

from aiorchestra.ai import CodexProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "codex", **overrides}
    return CodexProvider(config)


def test_codex_basic_invocation(monkeypatch):
    """Codex is invoked via ``exec --full-auto`` by default."""
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
    assert captured["cmd"][:2] == ["codex", "exec"]
    assert "--full-auto" in captured["cmd"]
    assert "fix the bug" in captured["cmd"]
    assert captured["cwd"] == "/tmp/repo"


def test_codex_custom_model(monkeypatch):
    """Model flag is forwarded when configured."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(model="o4-mini")
    provider.run("hello")

    assert "--model" in captured["cmd"]
    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "o4-mini"


def test_codex_sandbox_approval_mode(monkeypatch):
    """Sandbox-style approval modes map to --sandbox."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(approval_mode="workspace-write")
    provider.run("hello")

    assert "--full-auto" not in captured["cmd"]
    idx = captured["cmd"].index("--sandbox")
    assert captured["cmd"][idx + 1] == "workspace-write"


def test_codex_unknown_approval_mode(monkeypatch):
    """Unknown approval modes are omitted with a warning."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider(approval_mode="auto-edit")
    provider.run("hello")

    assert "--full-auto" not in captured["cmd"]
    assert "--sandbox" not in captured["cmd"]


def test_codex_failure(monkeypatch):
    """Non-zero exit code results in failure."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="codex error")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("hello")

    assert not result.success
    assert "codex error" in result.output


def test_codex_clarification(monkeypatch):
    """Clarification marker is detected in codex output."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="NEEDS_CLARIFICATION: What language?", stderr=""
        )

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("hello")

    assert result.success
    assert result.needs_clarification
    assert result.clarification_message == "What language?"


def test_codex_available(monkeypatch):
    """available() checks for codex on PATH."""
    monkeypatch.setattr(
        "aiorchestra.ai._cli.shutil.which",
        lambda name: "/usr/bin/codex" if name == "codex" else None,
    )
    assert _make_provider().available()

    monkeypatch.setattr("aiorchestra.ai._cli.shutil.which", lambda name: None)
    assert not _make_provider().available()


def test_create_provider_codex():
    """Factory creates CodexProvider for provider='codex'."""
    provider = create_provider({"provider": "codex"})
    assert isinstance(provider, CodexProvider)
