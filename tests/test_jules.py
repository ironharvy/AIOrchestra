"""Tests for the Google Jules cloud provider."""

import subprocess

from aiorchestra.ai import JulesProvider, create_provider


def _make_provider(**overrides):
    config = {"provider": "jules", "repo": "owner/repo", **overrides}
    return JulesProvider(config)


def test_jules_full_flow(monkeypatch):
    """Happy path: create session -> poll completed -> pull changes."""
    call_log = []

    def fake_run(cmd, *, capture_output=False, text=False, cwd=None):
        call_log.append(cmd)
        if cmd[1:3] == ["remote", "new"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="session-abc123\n", stderr="")
        if cmd[1:3] == ["remote", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="Status: completed\n", stderr="")
        if cmd[1:3] == ["remote", "pull"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="Changes pulled\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unknown")

    monkeypatch.setattr("aiorchestra.ai._jules.subprocess.run", fake_run)
    monkeypatch.setattr("aiorchestra.ai._jules.time.sleep", lambda _: None)

    provider = _make_provider()
    result = provider.run("implement feature X", cwd="/tmp/repo")

    assert result.success
    assert result.output == "Changes pulled\n"

    # Verify the correct commands were called.
    assert call_log[0][1:3] == ["remote", "new"]
    assert "--repo" in call_log[0]
    assert "--session" in call_log[0]
    assert call_log[1][1:3] == ["remote", "status"]
    assert "session-abc123" in call_log[1]
    assert call_log[2][1:3] == ["remote", "pull"]


def test_jules_session_creation_failure(monkeypatch):
    """Failure during session creation is handled."""

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="auth failed")

    monkeypatch.setattr("aiorchestra.ai._jules.subprocess.run", fake_run)

    provider = _make_provider()
    result = provider.run("implement feature")

    assert not result.success
    assert "auth failed" in result.output


def test_jules_session_failed_status(monkeypatch):
    """Jules session that reports failure."""
    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        if cmd[1:3] == ["remote", "new"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="sess-1\n", stderr="")
        if cmd[1:3] == ["remote", "status"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="Status: failed\nError: OOM", stderr=""
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("aiorchestra.ai._jules.subprocess.run", fake_run)
    monkeypatch.setattr("aiorchestra.ai._jules.time.sleep", lambda _: None)

    provider = _make_provider()
    result = provider.run("do something")

    assert not result.success
    assert "failed" in result.output.lower()


def test_jules_polling_multiple_rounds(monkeypatch):
    """Jules polls multiple times before completion."""
    poll_count = [0]

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["remote", "new"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="sess-2\n", stderr="")
        if cmd[1:3] == ["remote", "status"]:
            poll_count[0] += 1
            if poll_count[0] < 3:
                return subprocess.CompletedProcess(cmd, 0, stdout="Status: running\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="Status: completed\n", stderr="")
        if cmd[1:3] == ["remote", "pull"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unknown")

    monkeypatch.setattr("aiorchestra.ai._jules.subprocess.run", fake_run)
    monkeypatch.setattr("aiorchestra.ai._jules.time.sleep", lambda _: None)

    provider = _make_provider()
    result = provider.run("fix tests")

    assert result.success
    assert poll_count[0] == 3


def test_jules_timeout(monkeypatch):
    """Session that never completes times out."""
    elapsed = [0.0]

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["remote", "new"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="sess-3\n", stderr="")
        if cmd[1:3] == ["remote", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="Status: running\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_monotonic():
        val = elapsed[0]
        elapsed[0] += 60  # Jump 60s per call
        return val

    monkeypatch.setattr("aiorchestra.ai._jules.subprocess.run", fake_run)
    monkeypatch.setattr("aiorchestra.ai._jules.time.sleep", lambda _: None)
    monkeypatch.setattr("aiorchestra.ai._jules.time.monotonic", fake_monotonic)

    provider = _make_provider(timeout=120)
    result = provider.run("long task")

    assert not result.success
    assert "timed out" in result.output.lower()


def test_jules_pull_failure(monkeypatch):
    """Failure during pull is reported."""

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["remote", "new"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="sess-4\n", stderr="")
        if cmd[1:3] == ["remote", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="completed\n", stderr="")
        if cmd[1:3] == ["remote", "pull"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="merge conflict")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("aiorchestra.ai._jules.subprocess.run", fake_run)
    monkeypatch.setattr("aiorchestra.ai._jules.time.sleep", lambda _: None)

    provider = _make_provider()
    result = provider.run("update deps")

    assert not result.success
    assert "merge conflict" in result.output


def test_jules_clarification(monkeypatch):
    """Clarification marker in pull output is detected."""

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["remote", "new"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="sess-5\n", stderr="")
        if cmd[1:3] == ["remote", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="done\n", stderr="")
        if cmd[1:3] == ["remote", "pull"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="NEEDS_CLARIFICATION: Which DB?", stderr=""
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("aiorchestra.ai._jules.subprocess.run", fake_run)
    monkeypatch.setattr("aiorchestra.ai._jules.time.sleep", lambda _: None)

    provider = _make_provider()
    result = provider.run("migrate db")

    assert result.success
    assert result.needs_clarification
    assert result.clarification_message == "Which DB?"


def test_jules_available(monkeypatch):
    """available() checks for jules on PATH."""
    monkeypatch.setattr(
        "aiorchestra.ai._jules.shutil.which",
        lambda name: "/usr/bin/jules" if name == "jules" else None,
    )
    assert _make_provider().available()

    monkeypatch.setattr("aiorchestra.ai._jules.shutil.which", lambda name: None)
    assert not _make_provider().available()


def test_create_provider_jules():
    """Factory creates JulesProvider for provider='jules'."""
    provider = create_provider({"provider": "jules"})
    assert isinstance(provider, JulesProvider)
