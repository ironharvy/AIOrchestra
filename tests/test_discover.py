"""Tests for GitHub issue discovery."""

import json
import subprocess

from aiorchestra.stages.discover import discover_issues


def _completed_process(payload):
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
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
