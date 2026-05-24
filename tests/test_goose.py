"""Tests for the Goose CLI provider."""

import subprocess

from aiorchestra.ai import GooseProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "goose", **overrides}
    return GooseProvider(config)


def test_goose_basic_invocation(monkeypatch):
    """Goose runs `goose run --no-session -t <prompt>`."""
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
    cmd = captured["cmd"]
    assert cmd[:2] == ["goose", "run"]
    assert "--no-session" in cmd
    # Prompt is passed via -t.
    assert "-t" in cmd
    idx = cmd.index("-t")
    assert cmd[idx + 1] == "fix the bug"
    assert captured["cwd"] == "/tmp/repo"


def test_goose_session_opt_in(monkeypatch):
    """session=True keeps Goose's session file (omits --no-session)."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    _make_provider(session=True).run("hello")

    assert "--no-session" not in captured["cmd"]


def test_goose_llm_provider_and_model(monkeypatch):
    """llm_provider maps to --provider and model maps to --model."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    _make_provider(llm_provider="anthropic", model="claude-sonnet-4-6").run("hello")

    cmd = captured["cmd"]
    assert "--provider" in cmd
    assert cmd[cmd.index("--provider") + 1] == "anthropic"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-4-6"


def test_goose_no_model_flags_by_default(monkeypatch):
    """Without config, no --provider/--model flags are added."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    _make_provider().run("hello")

    assert "--provider" not in captured["cmd"]
    assert "--model" not in captured["cmd"]


def test_goose_failure(monkeypatch):
    """Non-zero exit code results in failure."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="goose error")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    result = _make_provider().run("hello")

    assert not result.success


def test_goose_via_registry():
    """The registry resolves the goose provider id."""
    provider = create_provider({"provider": "goose"})
    assert isinstance(provider, GooseProvider)
