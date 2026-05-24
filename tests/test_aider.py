"""Tests for the Aider CLI provider."""

import subprocess

from aiorchestra.ai import AiderProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "aider", **overrides}
    return AiderProvider(config)


def test_aider_basic_invocation(monkeypatch):
    """Aider runs with --message, scripting flags, and commits disabled."""
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
    assert cmd[0] == "aider"
    assert "--no-pretty" in cmd
    assert "--no-stream" in cmd
    assert "--yes-always" in cmd
    # The prompt is passed via --message.
    assert "--message" in cmd
    idx = cmd.index("--message")
    assert cmd[idx + 1] == "fix the bug"
    assert captured["cwd"] == "/tmp/repo"


def test_aider_disables_commits_by_default(monkeypatch):
    """Auto-commit is off by default so the pipeline owns committing."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    _make_provider().run("hello")

    assert "--no-auto-commits" in captured["cmd"]
    assert "--no-dirty-commits" in captured["cmd"]


def test_aider_auto_commits_opt_in(monkeypatch):
    """auto_commits=True restores Aider's native git behaviour."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    _make_provider(auto_commits=True).run("hello")

    assert "--no-auto-commits" not in captured["cmd"]
    assert "--no-dirty-commits" not in captured["cmd"]


def test_aider_yes_disabled(monkeypatch):
    """yes=False omits --yes-always."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    _make_provider(yes=False).run("hello")

    assert "--yes-always" not in captured["cmd"]


def test_aider_custom_model(monkeypatch):
    """Model flag is forwarded when configured."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    _make_provider(model="sonnet").run("hello")

    assert "--model" in captured["cmd"]
    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "sonnet"


def test_aider_failure(monkeypatch):
    """Non-zero exit code results in failure."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="aider error")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", fake_run)

    result = _make_provider().run("hello")

    assert not result.success


def test_aider_via_registry():
    """The registry resolves the aider provider id."""
    provider = create_provider({"provider": "aider"})
    assert isinstance(provider, AiderProvider)
