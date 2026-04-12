"""Tests for the publish stage — PR creation and existing-PR detection."""

import types

from aiorchestra.stages import publish as pub_mod
from aiorchestra.stages.publish import _build_pr_body, _create_pr, _find_existing_pr, publish

ISSUE = {"number": 24, "title": "Add multi-level verbose logging"}
ISSUE_RICH = {
    "number": 24,
    "title": "Add multi-level verbose logging",
    "body": "We need verbose, debug, and trace levels.",
    "labels": ["enhancement", "logging"],
}
REPO = "owner/repo"
BRANCH = "claude/24"
REPO_ROOT = "/tmp/fake-repo"


def _make_result(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# _find_existing_pr
# ---------------------------------------------------------------------------


def test_find_existing_pr_returns_url_when_pr_exists(monkeypatch):
    url = "https://github.com/owner/repo/pull/25"
    monkeypatch.setattr(
        pub_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: _make_result(stdout=url + "\n"),
    )

    assert _find_existing_pr(REPO, BRANCH, REPO_ROOT) == url


def test_find_existing_pr_returns_none_when_no_pr(monkeypatch):
    monkeypatch.setattr(
        pub_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: _make_result(returncode=1, stderr="no pull requests"),
    )

    assert _find_existing_pr(REPO, BRANCH, REPO_ROOT) is None


def test_find_existing_pr_returns_none_on_empty_stdout(monkeypatch):
    monkeypatch.setattr(
        pub_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: _make_result(stdout=""),
    )

    assert _find_existing_pr(REPO, BRANCH, REPO_ROOT) is None


# ---------------------------------------------------------------------------
# _create_pr — reuses existing PR
# ---------------------------------------------------------------------------


def test_create_pr_returns_existing_pr_url(monkeypatch):
    """When a PR already exists, _create_pr should return its URL without creating a new one."""
    existing_url = "https://github.com/owner/repo/pull/25"
    commands_run = []

    def fake_run_command(cmd, cwd=None, logger=None):
        commands_run.append(cmd)
        # First call is _find_existing_pr (gh pr view)
        if "view" in cmd:
            return _make_result(stdout=existing_url + "\n")
        # Should never reach gh pr create
        return _make_result(returncode=1, stderr="should not be called")

    monkeypatch.setattr(pub_mod, "run_command", fake_run_command)

    result = _create_pr(REPO, BRANCH, ISSUE, REPO_ROOT)
    assert result == existing_url
    # Verify gh pr create was never called
    assert not any("create" in cmd for cmd in commands_run)


def test_create_pr_creates_new_when_none_exists(monkeypatch):
    """When no PR exists, _create_pr should create one."""
    new_url = "https://github.com/owner/repo/pull/30"

    def fake_run_command(cmd, *, cwd=None, check=False, shell=None, logger=None):
        if "view" in cmd:
            return _make_result(returncode=1, stderr="no pull requests found")
        if "create" in cmd:
            return _make_result(stdout=new_url + "\n")
        # git diff --stat for PR body builder
        if "diff" in cmd:
            return _make_result(stdout=" file.py | 2 +-\n 1 file changed\n")
        return _make_result()

    monkeypatch.setattr(pub_mod, "run_command", fake_run_command)
    monkeypatch.setattr("aiorchestra.stages._shell.run_command", fake_run_command)

    result = _create_pr(REPO, BRANCH, ISSUE, REPO_ROOT)
    assert result == new_url


# ---------------------------------------------------------------------------
# _build_pr_body
# ---------------------------------------------------------------------------


def test_build_pr_body_minimal(monkeypatch):
    """A minimal issue (no body/labels) still produces a valid PR body."""
    monkeypatch.setattr(
        pub_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: _make_result(stdout=""),
    )
    body = _build_pr_body(ISSUE, REPO_ROOT)
    assert "Automated implementation for #24" in body
    assert "Closes #24" in body
    # No issue-description or labels sections
    assert "## Issue description" not in body
    assert "**Labels:**" not in body


def test_build_pr_body_rich(monkeypatch):
    """A rich issue includes description, diff stats, and labels."""
    diff_stat = " src/log.py | 10 +++++++---\n 1 file changed, 7 insertions(+), 3 deletions(-)"

    monkeypatch.setattr(
        pub_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: _make_result(stdout=diff_stat),
    )
    body = _build_pr_body(ISSUE_RICH, REPO_ROOT)
    assert "## Issue description" in body
    assert "verbose, debug, and trace levels" in body
    assert "## Changes" in body
    assert "src/log.py" in body
    assert "`enhancement`" in body
    assert "`logging`" in body
    assert "Closes #24" in body


# ---------------------------------------------------------------------------
# publish — end-to-end with existing PR
# ---------------------------------------------------------------------------


def test_publish_with_existing_pr_url_skips_creation(monkeypatch):
    """When pr_url is passed, publish pushes but skips PR creation entirely."""
    calls = []

    def fake_run_command(cmd, *, cwd=None, check=False, shell=None, logger=None):
        calls.append(cmd)
        if "status" in cmd:
            return _make_result(stdout="M file.py\n")
        if "add" in cmd or "commit" in cmd:
            return _make_result()
        if "diff" in cmd:
            return _make_result(stdout=" file.py | 2 +-\n 1 file changed\n")
        if "log" in cmd:
            return _make_result(stdout="abc123 some commit\n")
        if "push" in cmd:
            return _make_result()
        return _make_result()

    monkeypatch.setattr(pub_mod, "run_command", fake_run_command)
    monkeypatch.setattr("aiorchestra.stages._shell.run_command", fake_run_command)

    result = publish(REPO, BRANCH, ISSUE, REPO_ROOT, pr_url="https://github.com/owner/repo/pull/25")
    assert result == "https://github.com/owner/repo/pull/25"
    # gh pr create / gh pr view should never be called
    assert not any("pr" in str(cmd) for cmd in calls)


def test_publish_without_pr_url_detects_existing(monkeypatch):
    """When no pr_url is passed but a PR exists, publish detects and returns it."""
    existing_url = "https://github.com/owner/repo/pull/25"

    def fake_run_command(cmd, *, cwd=None, check=False, shell=None, logger=None):
        if "status" in cmd:
            return _make_result(stdout="M file.py\n")
        if "add" in cmd or "commit" in cmd:
            return _make_result()
        if "diff" in cmd:
            return _make_result(stdout=" file.py | 2 +-\n 1 file changed\n")
        if "log" in cmd:
            return _make_result(stdout="abc123 some commit\n")
        if "push" in cmd:
            return _make_result()
        if "view" in cmd:
            return _make_result(stdout=existing_url + "\n")
        return _make_result()

    monkeypatch.setattr(pub_mod, "run_command", fake_run_command)
    monkeypatch.setattr("aiorchestra.stages._shell.run_command", fake_run_command)

    result = publish(REPO, BRANCH, ISSUE, REPO_ROOT)
    assert result == existing_url
