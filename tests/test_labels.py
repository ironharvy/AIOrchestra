"""Tests for label management and ensure_labels."""

import json
import subprocess

from aiorchestra.stages.labels import (
    MANAGED_LABELS,
    LabelDef,
    ensure_labels,
)


def _completed_process(payload="", returncode=0):
    stdout = json.dumps(payload) if not isinstance(payload, str) else payload
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr="")


def _failed_process(stderr="error"):
    return subprocess.CompletedProcess(args=["gh"], returncode=1, stdout="", stderr=stderr)


def test_ensure_labels_creates_missing(monkeypatch):
    """Labels that don't exist in the repo should be created."""
    commands_run = []

    def fake_run(cmd, logger=None):
        commands_run.append(cmd)
        if cmd[1] == "label" and cmd[2] == "list":
            return _completed_process([])  # no existing labels
        if cmd[1] == "label" and cmd[2] == "create":
            return _completed_process("")
        return _failed_process()

    monkeypatch.setattr("aiorchestra.stages.labels.run_command", fake_run)

    labels = (LabelDef("test-label", "ff0000", "A test label"),)
    created = ensure_labels("owner/repo", labels=labels)

    assert created == ["test-label"]
    create_cmds = [c for c in commands_run if c[1] == "label" and c[2] == "create"]
    assert len(create_cmds) == 1
    assert "test-label" in create_cmds[0]


def test_ensure_labels_skips_existing(monkeypatch):
    """Labels that already exist should not be re-created."""

    def fake_run(cmd, logger=None):
        if cmd[1] == "label" and cmd[2] == "list":
            return _completed_process([{"name": "agent-working"}])
        return _failed_process()

    monkeypatch.setattr("aiorchestra.stages.labels.run_command", fake_run)

    labels = (LabelDef("agent-working", "fbca04", "desc"),)
    created = ensure_labels("owner/repo", labels=labels)

    assert created == []


def test_ensure_labels_dry_run(monkeypatch):
    """Dry-run should report labels without creating them."""

    def fake_run(cmd, logger=None):
        if cmd[1] == "label" and cmd[2] == "list":
            return _completed_process([])
        raise AssertionError("Should not create labels in dry-run")

    monkeypatch.setattr("aiorchestra.stages.labels.run_command", fake_run)

    labels = (LabelDef("new-label", "00ff00", "desc"),)
    created = ensure_labels("owner/repo", labels=labels, dry_run=True)

    assert created == ["new-label"]


def test_ensure_labels_case_insensitive(monkeypatch):
    """Label matching should be case-insensitive."""

    def fake_run(cmd, logger=None):
        if cmd[1] == "label" and cmd[2] == "list":
            return _completed_process([{"name": "Agent-Working"}])
        return _failed_process()

    monkeypatch.setattr("aiorchestra.stages.labels.run_command", fake_run)

    labels = (LabelDef("agent-working", "fbca04", "desc"),)
    created = ensure_labels("owner/repo", labels=labels)

    assert created == []


def test_ensure_labels_handles_create_failure(monkeypatch):
    """A failed create should warn but not crash."""

    def fake_run(cmd, logger=None):
        if cmd[1] == "label" and cmd[2] == "list":
            return _completed_process([])
        if cmd[1] == "label" and cmd[2] == "create":
            return _failed_process("already exists")
        return _failed_process()

    monkeypatch.setattr("aiorchestra.stages.labels.run_command", fake_run)

    labels = (LabelDef("dup-label", "aabbcc", "desc"),)
    created = ensure_labels("owner/repo", labels=labels)

    assert created == []


def test_ensure_labels_defaults_to_managed_labels(monkeypatch):
    """Calling with no labels arg should use MANAGED_LABELS."""

    def fake_run(cmd, logger=None):
        if cmd[1] == "label" and cmd[2] == "list":
            return _completed_process([])
        if cmd[1] == "label" and cmd[2] == "create":
            return _completed_process("")
        return _failed_process()

    monkeypatch.setattr("aiorchestra.stages.labels.run_command", fake_run)

    created = ensure_labels("owner/repo")

    assert len(created) == len(MANAGED_LABELS)
