"""Tests for the agent clarification / deferral flow and issue lifecycle."""

import json
import os
import subprocess
import types

from aiorchestra.ai.claude import InvokeResult, _parse_clarification
from aiorchestra.pipeline import Pipeline, _DEFERRED
from aiorchestra.stages.clarification import CLARIFICATION_LABEL
from aiorchestra.stages.labels import LABEL_WORKING


# ---------------------------------------------------------------------------
# InvokeResult / parsing
# ---------------------------------------------------------------------------

def test_parse_clarification_detects_marker():
    text = "NEEDS_CLARIFICATION: Which database adapter should I use?"
    result = _parse_clarification(text)
    assert result.needs_clarification is True
    assert result.clarification_message == "Which database adapter should I use?"
    assert result.success is True


def test_parse_clarification_detects_marker_after_text():
    text = (
        "I've analyzed the issue and found an ambiguity.\n"
        "NEEDS_CLARIFICATION: Should the endpoint return 404 or 204 when empty?"
    )
    result = _parse_clarification(text)
    assert result.needs_clarification is True
    assert "404 or 204" in result.clarification_message


def test_parse_clarification_ignores_normal_output():
    text = "I've implemented the requested changes to the API handler."
    result = _parse_clarification(text)
    assert result.needs_clarification is False
    assert result.clarification_message == ""
    assert result.success is True


def test_parse_clarification_requires_exact_marker():
    text = "This NEEDS_CLARIFICATION but I went ahead anyway."
    result = _parse_clarification(text)
    # The marker must be at the start of a line followed by a colon
    # "This NEEDS_CLARIFICATION but..." does not match because it's not at line start
    assert result.needs_clarification is False


# ---------------------------------------------------------------------------
# discover: needs-clarification exclusion
# ---------------------------------------------------------------------------

def _completed_process(payload):
    return subprocess.CompletedProcess(
        args=["gh"], returncode=0, stdout=json.dumps(payload), stderr="",
    )


def test_discover_excludes_needs_clarification_issues(monkeypatch):
    from aiorchestra.stages.discover import discover_issues

    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 1,
                    "title": "Ready issue",
                    "body": "",
                    "labels": [{"name": "claude"}],
                    "assignees": [],
                },
                {
                    "number": 2,
                    "title": "Waiting for human",
                    "body": "",
                    "labels": [
                        {"name": "claude"},
                        {"name": CLARIFICATION_LABEL},
                    ],
                    "assignees": [],
                },
            ]
        ),
    )

    issues = discover_issues(
        "owner/repo", "claude", agent_label="claude", retries=1, delay=0,
    )

    assert len(issues) == 1
    assert issues[0]["number"] == 1


def test_discover_returns_empty_when_all_need_clarification(monkeypatch):
    from aiorchestra.stages.discover import discover_issues

    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 5,
                    "title": "Blocked",
                    "body": "",
                    "labels": [
                        {"name": "claude"},
                        {"name": CLARIFICATION_LABEL},
                    ],
                    "assignees": [],
                },
            ]
        ),
    )

    issues = discover_issues(
        "owner/repo", "claude", agent_label="claude", retries=1, delay=0,
    )

    assert issues == []


# ---------------------------------------------------------------------------
# clarification stage: comment + label
# ---------------------------------------------------------------------------

def test_request_clarification_posts_comment_and_label(monkeypatch):
    from aiorchestra.stages import clarification as clar_mod
    from aiorchestra.stages import labels as labels_mod
    from aiorchestra.stages.clarification import request_clarification

    gh_calls = []

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        gh_calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(clar_mod, "run_command", fake_run)
    monkeypatch.setattr(labels_mod, "run_command", fake_run)

    ok = request_clarification(
        "owner/repo",
        {"number": 42, "title": "Ambiguous task"},
        "Which DB adapter should I use?",
    )

    assert ok is True
    assert len(gh_calls) == 2

    # First call: comment
    comment_cmd = gh_calls[0]
    assert "comment" in comment_cmd
    assert "42" in comment_cmd
    assert any("DB adapter" in arg for arg in comment_cmd)

    # Second call: label
    label_cmd = gh_calls[1]
    assert CLARIFICATION_LABEL in label_cmd


def test_request_clarification_returns_false_on_comment_failure(monkeypatch):
    from aiorchestra.stages import clarification as clar_mod
    from aiorchestra.stages import labels as labels_mod
    from aiorchestra.stages.clarification import request_clarification

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        if "comment" in cmd:
            return types.SimpleNamespace(returncode=1, stdout="", stderr="auth error")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(clar_mod, "run_command", fake_run)
    monkeypatch.setattr(labels_mod, "run_command", fake_run)

    ok = request_clarification(
        "owner/repo",
        {"number": 1, "title": "Test"},
        "question",
    )
    assert ok is False


# ---------------------------------------------------------------------------
# Pipeline: end-to-end deferred flow
# ---------------------------------------------------------------------------

def test_pipeline_defers_issue_on_clarification(monkeypatch, tmp_path):
    """When the agent requests clarification, the pipeline should defer the
    issue (not fail) and continue to the next one."""
    calls = []

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 1},
            "ci": {"enabled": False},
            "review": {"enabled": False},
        },
    )

    clarification_msg = "Should this be sync or async?"

    def fake_implement(issue, config, prompt_name="implement", error_text=None, repo_root=None, osint_context=""):
        calls.append(("implement", issue["number"]))
        if issue["number"] == 10:
            return InvokeResult(
                success=True,
                output=f"NEEDS_CLARIFICATION: {clarification_msg}",
                needs_clarification=True,
                clarification_message=clarification_msg,
            )
        return InvokeResult(success=True)

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, config: "")
    monkeypatch.setattr("aiorchestra.pipeline._has_changes", lambda repo_root: True)
    monkeypatch.setattr(
        "aiorchestra.pipeline.validate", lambda config, repo_root=None: (True, None),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.publish",
        lambda repo, branch, issue, repo_root, pr_url=None: "https://example.test/pr/1",
    )

    # Mock request_clarification so we don't shell out
    clarification_calls = []

    def fake_request_clarification(repo, issue, message):
        clarification_calls.append((repo, issue["number"], message))
        return True

    monkeypatch.setattr(
        "aiorchestra.pipeline.request_clarification",
        fake_request_clarification,
    )
    monkeypatch.setattr("aiorchestra.pipeline.add_label", lambda repo, number, label: True)
    monkeypatch.setattr("aiorchestra.pipeline.remove_label", lambda repo, number, label: True)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        parallel=False,
    )

    issues = [
        {"number": 10, "title": "Ambiguous one"},
        {"number": 20, "title": "Clear one"},
    ]

    # Pipeline should succeed (0) even though issue 10 was deferred
    assert pipeline.run(issues=issues) == 0

    # Issue 10 triggered clarification, issue 20 was processed normally
    assert ("implement", 10) in calls
    assert ("implement", 20) in calls
    assert len(clarification_calls) == 1
    assert clarification_calls[0] == (
        "owner/repo", 10, clarification_msg,
    )


def test_pipeline_process_issue_returns_deferred(monkeypatch, tmp_path):
    """_process_issue returns _DEFERRED sentinel when clarification is needed."""
    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 1},
            "ci": {"enabled": False},
            "review": {"enabled": False},
        },
    )

    def fake_implement(issue, config, prompt_name="implement", error_text=None, repo_root=None, osint_context=""):
        return InvokeResult(
            success=True,
            needs_clarification=True,
            clarification_message="Which endpoint?",
        )

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, config: "")
    monkeypatch.setattr(
        "aiorchestra.pipeline.request_clarification",
        lambda repo, issue, msg: True,
    )

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    result = pipeline._process_issue({"number": 1, "title": "Test"})
    assert result == _DEFERRED


# ---------------------------------------------------------------------------
# discover: agent-working exclusion
# ---------------------------------------------------------------------------

def test_discover_excludes_agent_working_issues(monkeypatch):
    from aiorchestra.stages.discover import discover_issues

    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 1,
                    "title": "Available",
                    "body": "",
                    "labels": [{"name": "claude"}],
                    "assignees": [],
                },
                {
                    "number": 2,
                    "title": "Already being worked on",
                    "body": "",
                    "labels": [
                        {"name": "claude"},
                        {"name": LABEL_WORKING},
                    ],
                    "assignees": [],
                },
                {
                    "number": 3,
                    "title": "Waiting for human",
                    "body": "",
                    "labels": [
                        {"name": "claude"},
                        {"name": CLARIFICATION_LABEL},
                    ],
                    "assignees": [],
                },
            ]
        ),
    )

    issues = discover_issues(
        "owner/repo", "claude", agent_label="claude", retries=1, delay=0,
    )

    assert len(issues) == 1
    assert issues[0]["number"] == 1


# ---------------------------------------------------------------------------
# Label lifecycle: _claim_and_process (sequential mode)
# ---------------------------------------------------------------------------

def test_sequential_mode_adds_and_removes_working_label(monkeypatch, tmp_path):
    """In sequential mode, _claim_and_process should add agent-working before
    processing and remove it after, regardless of outcome."""
    label_ops = []

    def track_add(repo, number, label):
        label_ops.append(("add", number, label))
        return True

    def track_remove(repo, number, label):
        label_ops.append(("remove", number, label))
        return True

    monkeypatch.setattr("aiorchestra.pipeline.add_label", track_add)
    monkeypatch.setattr("aiorchestra.pipeline.remove_label", track_remove)
    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 1},
            "ci": {"enabled": False},
            "review": {"enabled": False},
        },
    )
    monkeypatch.setattr("aiorchestra.pipeline._has_changes", lambda repo_root: True)
    monkeypatch.setattr(
        "aiorchestra.pipeline.implement",
        lambda issue, config, prompt_name="implement", error_text=None, repo_root=None, osint_context="":
            InvokeResult(success=True),
    )
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, config: "")
    monkeypatch.setattr(
        "aiorchestra.pipeline.validate",
        lambda config, repo_root=None: (True, None),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.publish",
        lambda repo, branch, issue, repo_root, pr_url=None: "https://example.test/pr/1",
    )

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        parallel=False,
    )

    assert pipeline.run(issues=[{"number": 7, "title": "Test"}]) == 0

    assert ("add", 7, LABEL_WORKING) in label_ops
    assert ("remove", 7, LABEL_WORKING) in label_ops
    # add must come before remove
    add_idx = label_ops.index(("add", 7, LABEL_WORKING))
    remove_idx = label_ops.index(("remove", 7, LABEL_WORKING))
    assert add_idx < remove_idx


def test_sequential_mode_removes_label_on_failure(monkeypatch, tmp_path):
    """agent-working label must be removed even when the issue fails."""
    label_ops = []

    monkeypatch.setattr(
        "aiorchestra.pipeline.add_label",
        lambda repo, number, label: label_ops.append(("add", number, label)) or True,
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.remove_label",
        lambda repo, number, label: label_ops.append(("remove", number, label)) or True,
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 1},
            "ci": {"enabled": False},
            "review": {"enabled": False},
        },
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.implement",
        lambda issue, config, prompt_name="implement", error_text=None, repo_root=None, osint_context="":
            InvokeResult(success=False),
    )
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, config: "")

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        parallel=False,
    )

    # Failure return code
    assert pipeline.run(issues=[{"number": 5, "title": "Broken"}]) == 1

    # Label was still cleaned up
    assert ("add", 5, LABEL_WORKING) in label_ops
    assert ("remove", 5, LABEL_WORKING) in label_ops


# ---------------------------------------------------------------------------
# Parallel mode: fork-per-issue
# ---------------------------------------------------------------------------

def test_parallel_mode_forks_per_issue(monkeypatch, tmp_path):
    """In parallel mode, each issue gets its own child process."""
    forked_issues = []
    waited_pids = []

    # Simulate fork: return a fake pid to the parent
    fake_pid = iter([100, 200])

    def fake_fork():
        pid = next(fake_pid)
        forked_issues.append(pid)
        return pid  # always parent path

    def fake_waitpid(pid, flags):
        waited_pids.append(pid)
        # Return (pid, status=0) — child succeeded
        return pid, 0

    monkeypatch.setattr(os, "fork", fake_fork)
    monkeypatch.setattr(os, "waitpid", fake_waitpid)
    monkeypatch.setattr(os, "waitstatus_to_exitcode", lambda status: status)
    monkeypatch.setattr("aiorchestra.pipeline.add_label", lambda repo, number, label: True)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        parallel=True,
    )

    issues = [
        {"number": 10, "title": "Issue A"},
        {"number": 20, "title": "Issue B"},
    ]

    result = pipeline.run(issues=issues)

    assert result == 0
    assert len(forked_issues) == 2
    assert set(waited_pids) == {100, 200}


def test_parallel_mode_reports_child_failure(monkeypatch, tmp_path):
    """If a child exits non-zero, the parent should report failure."""
    fake_pid = iter([100])

    monkeypatch.setattr(os, "fork", lambda: next(fake_pid))
    monkeypatch.setattr(os, "waitpid", lambda pid, flags: (pid, 1))
    monkeypatch.setattr(os, "waitstatus_to_exitcode", lambda status: status)
    monkeypatch.setattr("aiorchestra.pipeline.add_label", lambda repo, number, label: True)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        parallel=True,
    )

    result = pipeline.run(issues=[{"number": 10, "title": "Failing"}])
    assert result == 1


def test_parallel_dry_run_does_not_fork(monkeypatch):
    """Dry run should not fork any child processes."""
    fork_called = False

    def no_fork():
        nonlocal fork_called
        fork_called = True
        return 0

    monkeypatch.setattr(os, "fork", no_fork)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        parallel=True,
        dry_run=True,
    )

    result = pipeline.run(issues=[{"number": 1, "title": "Dry"}])
    assert result == 0
    assert not fork_called
