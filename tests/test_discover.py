"""Tests for GitHub issue discovery."""

import json
import subprocess

from aiorchestra.stages.discover import discover_all_issues, discover_issues


def _completed_process(payload):
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def _failed_process(stderr="error"):
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=1,
        stdout="",
        stderr=stderr,
    )


def test_discover_normalizes_issue_metadata(monkeypatch):
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 7,
                    "title": "Implement feature",
                    "body": "Details",
                    "labels": [{"name": "Claude"}, {"name": "automation"}],
                    "assignees": [{"login": "CodexBot"}],
                }
            ]
        ),
    )

    issues = discover_issues(
        "owner/repo",
        "automation",
        agent_label="claude-code",
        retries=1,
        delay=0,
    )

    assert issues == [
        {
            "number": 7,
            "title": "Implement feature",
            "body": "Details",
            "labels": ["claude", "automation"],
            "assignees": ["codexbot"],
        }
    ]


def test_discover_skips_awaiting_review(monkeypatch):
    """Issues with the awaiting-review label should not be returned."""
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 1,
                    "title": "Already reviewed",
                    "body": "",
                    "labels": [{"name": "claude"}, {"name": "awaiting-review"}],
                    "assignees": [],
                },
                {
                    "number": 2,
                    "title": "Ready",
                    "body": "",
                    "labels": [{"name": "claude"}],
                    "assignees": [],
                },
            ]
        ),
    )

    issues = discover_issues("owner/repo", "claude", retries=1, delay=0)
    assert len(issues) == 1
    assert issues[0]["number"] == 2


def test_discover_skips_agent_failed(monkeypatch):
    """Issues with the agent-failed label should not be returned."""
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 3,
                    "title": "Previously failed",
                    "body": "",
                    "labels": [{"name": "claude"}, {"name": "agent-failed"}],
                    "assignees": [],
                },
            ]
        ),
    )

    issues = discover_issues("owner/repo", "claude", retries=1, delay=0)
    assert issues == []


def test_discover_issue_number_requires_matching_agent_label(monkeypatch):
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            {
                "number": 42,
                "title": "Wrong label",
                "body": "Details",
                "labels": [{"name": "bug"}],
                "assignees": [{"login": "claude"}],
            }
        ),
    )

    issues = discover_issues(
        "owner/repo",
        "automation",
        issue_number=42,
        agent_label="claude",
        retries=1,
        delay=0,
    )

    assert issues == []


# ---------------------------------------------------------------------------
# discover_all_issues
# ---------------------------------------------------------------------------


def test_discover_all_groups_by_repo(monkeypatch):
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 1,
                    "title": "Alpha",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}],
                    "assignees": [],
                    "repository": {"nameWithOwner": "owner/repo-a"},
                },
                {
                    "number": 5,
                    "title": "Beta",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}, {"name": "claude"}],
                    "assignees": [],
                    "repository": {"nameWithOwner": "owner/repo-b"},
                },
                {
                    "number": 2,
                    "title": "Gamma",
                    "body": "details",
                    "labels": [{"name": "aiorchestra"}],
                    "assignees": [{"login": "alice"}],
                    "repository": {"nameWithOwner": "owner/repo-a"},
                },
            ]
        ),
    )

    result = discover_all_issues(owner="@me")

    assert set(result.keys()) == {"owner/repo-a", "owner/repo-b"}
    assert len(result["owner/repo-a"]) == 2
    assert len(result["owner/repo-b"]) == 1
    assert result["owner/repo-a"][0]["number"] == 1
    assert result["owner/repo-a"][1]["number"] == 2
    assert result["owner/repo-b"][0]["labels"] == ["aiorchestra", "claude"]


def test_discover_all_returns_empty_on_no_results(monkeypatch):
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process([]),
    )

    assert discover_all_issues() == {}


def test_discover_all_returns_empty_on_gh_failure(monkeypatch):
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _failed_process("fatal: auth required"),
    )

    assert discover_all_issues() == {}


def test_discover_all_skips_entries_without_repository(monkeypatch):
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 1,
                    "title": "No repo",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}],
                    "assignees": [],
                },
            ]
        ),
    )

    assert discover_all_issues() == {}


def test_discover_all_skips_issues_with_skip_labels(monkeypatch):
    """discover_all_issues must filter out issues with outcome/working labels."""
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 1,
                    "title": "In review",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}, {"name": "awaiting-review"}],
                    "assignees": [],
                    "repository": {"nameWithOwner": "owner/repo-a"},
                },
                {
                    "number": 2,
                    "title": "Ready",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}],
                    "assignees": [],
                    "repository": {"nameWithOwner": "owner/repo-a"},
                },
                {
                    "number": 3,
                    "title": "Failed",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}, {"name": "agent-failed"}],
                    "assignees": [],
                    "repository": {"nameWithOwner": "owner/repo-b"},
                },
            ]
        ),
    )

    result = discover_all_issues(owner="@me")
    assert set(result.keys()) == {"owner/repo-a"}
    assert len(result["owner/repo-a"]) == 1
    assert result["owner/repo-a"][0]["number"] == 2


def test_discover_uses_dispatch_label_for_gh_query(monkeypatch):
    """The gh query must use DISPATCH_LABEL, not the config label."""
    captured_cmds = []

    def fake_run(cmd, logger=None):
        captured_cmds.append(cmd)
        return _completed_process(
            [
                {
                    "number": 1,
                    "title": "Build landing page",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}, {"name": "codex"}],
                    "assignees": [],
                }
            ]
        )

    monkeypatch.setattr("aiorchestra.stages.discover.run_command", fake_run)

    issues = discover_issues(
        "owner/flower_shop",
        "claude",
        agent_label="codex",
        retries=1,
        delay=0,
    )

    assert len(issues) == 1
    assert issues[0]["number"] == 1
    assert "--label" in captured_cmds[0]
    label_idx = captured_cmds[0].index("--label")
    assert captured_cmds[0][label_idx + 1] == "aiorchestra"


def test_discover_without_filter_returns_all_ready_issues(monkeypatch):
    """Without an agent label, every non-skipped issue should be returned."""
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 1,
                    "title": "Codex issue",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}, {"name": "codex"}],
                    "assignees": [],
                },
                {
                    "number": 2,
                    "title": "Claude issue",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}, {"name": "claude"}],
                    "assignees": [],
                },
                {
                    "number": 3,
                    "title": "Unlabelled (dispatch only)",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}],
                    "assignees": [],
                },
                {
                    "number": 4,
                    "title": "Already reviewed",
                    "body": "",
                    "labels": [{"name": "aiorchestra"}, {"name": "awaiting-review"}],
                    "assignees": [],
                },
            ]
        ),
    )

    issues = discover_issues("owner/repo", retries=1, delay=0)

    assert [i["number"] for i in issues] == [1, 2, 3]


def test_discover_normalizes_comments(monkeypatch):
    """Issue comments should be extracted and normalized."""
    monkeypatch.setattr(
        "aiorchestra.stages.discover.run_command",
        lambda cmd, logger=None: _completed_process(
            [
                {
                    "number": 10,
                    "title": "With comments",
                    "body": "Details",
                    "labels": [{"name": "claude"}],
                    "assignees": [],
                    "comments": [
                        {
                            "author": {"login": "alice"},
                            "body": "Try approach X",
                            "createdAt": "2025-01-01T00:00:00Z",
                        },
                        {
                            "author": {"login": "bob"},
                            "body": "I agree",
                            "createdAt": "2025-01-02T00:00:00Z",
                        },
                    ],
                }
            ]
        ),
    )

    issues = discover_issues("owner/repo", "claude", retries=1, delay=0)
    assert len(issues) == 1
    assert "comments" in issues[0]
    assert len(issues[0]["comments"]) == 2
    assert issues[0]["comments"][0] == {"author": "alice", "body": "Try approach X"}
    assert issues[0]["comments"][1] == {"author": "bob", "body": "I agree"}
