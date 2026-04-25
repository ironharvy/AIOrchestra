"""Tests for the publish stage — PR creation and existing-PR detection."""

import subprocess
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
    body = _build_pr_body(ISSUE, REPO_ROOT, REPO)
    assert "Automated implementation for #24" in body
    assert "**Issue:** https://github.com/owner/repo/issues/24" in body
    assert "Closes #24" in body
    # No inlined issue body, no labels
    assert "## Issue description" not in body
    assert "**Labels:**" not in body


def test_build_pr_body_rich(monkeypatch):
    """A rich issue links to the issue, includes diff stats and labels; no full issue body."""
    diff_stat = " src/log.py | 10 +++++++---\n 1 file changed, 7 insertions(+), 3 deletions(-)"

    monkeypatch.setattr(
        pub_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: _make_result(stdout=diff_stat),
    )
    body = _build_pr_body(ISSUE_RICH, REPO_ROOT, REPO)
    assert "verbose, debug, and trace levels" not in body
    assert "**Issue:** https://github.com/owner/repo/issues/24" in body
    assert "## Changes" in body
    assert "src/log.py" in body
    assert "`enhancement`" in body
    assert "`logging`" in body
    assert "Closes #24" in body


def test_build_pr_body_truncates_diff_stat(monkeypatch):
    """Long issue bodies are not copied; only diff --stat is line-capped in the PR."""
    issue = {
        "number": 24,
        "title": "Add multi-level verbose logging",
        "body": "A" * 80,
    }
    file_lines = [f" src/module_{i:03d}.py | 1 +" for i in range(6)]
    diff_stat = "\n".join(
        file_lines
        + [
            " 6 files changed, 6 insertions(+)",
        ]
    )

    monkeypatch.setattr(pub_mod, "_MAX_DIFF_STAT_LINES", 2)
    monkeypatch.setattr(pub_mod, "_MAX_PR_BODY_CHARS", 10_000)
    monkeypatch.setattr(
        pub_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: _make_result(stdout=diff_stat),
    )

    body = _build_pr_body(issue, REPO_ROOT, REPO)

    assert "A" * 20 not in body
    assert "src/module_000.py" in body
    assert "src/module_001.py" in body
    assert "src/module_002.py" not in body
    assert "Diff stat truncated to first 2 lines" in body
    assert "6 files changed, 6 insertions(+)" in body


def test_build_pr_body_applies_final_body_cap(monkeypatch):
    """A final safety cap should keep the PR body under the configured limit."""
    issue = {
        "number": 24,
        "title": "Add multi-level verbose logging",
        "body": "B" * 2000,
    }

    long_diff = "\n".join([f" src/f{i:03d}.py | 1 +" for i in range(30)]) + "\n 30 files changed\n"
    monkeypatch.setattr(pub_mod, "_MAX_PR_BODY_CHARS", 320)
    monkeypatch.setattr(pub_mod, "_MAX_DIFF_STAT_LINES", 50)
    monkeypatch.setattr(
        pub_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: _make_result(stdout=long_diff),
    )

    body = _build_pr_body(issue, REPO_ROOT, REPO)

    assert "B" * 50 not in body
    assert len(body) <= 320
    assert "[PR body truncated to 320 characters.]" in body
    assert body.endswith("Closes #24")


def test_create_pr_retries_transient_failure(monkeypatch):
    """Transient GitHub transport failures should be retried once."""
    calls = []
    new_url = "https://github.com/owner/repo/pull/30"

    def fake_run_command_or_fail(cmd, *, error_msg, cwd=None, shell=None, logger=None):
        calls.append(cmd)
        if len(calls) == 1:
            raise pub_mod.CommandError(
                "PR creation failed: connection reset by peer",
                subprocess.CompletedProcess(cmd, 1, stdout="", stderr="connection reset by peer"),
            )
        return _make_result(stdout=new_url + "\n")

    monkeypatch.setattr(pub_mod, "_build_pr_body", lambda issue, repo_root, repo: "short body")
    monkeypatch.setattr(pub_mod, "_find_existing_pr", lambda repo, branch, repo_root: None)
    monkeypatch.setattr(pub_mod, "run_command_or_fail", fake_run_command_or_fail)
    monkeypatch.setattr(pub_mod.time, "sleep", lambda _: None)

    result = _create_pr(REPO, BRANCH, ISSUE, REPO_ROOT)

    assert result == new_url
    assert len(calls) == 2


def test_create_pr_does_not_retry_body_too_long(monkeypatch):
    """Deterministic content failures should fail immediately."""
    calls = []

    def fake_run_command_or_fail(cmd, *, error_msg, cwd=None, shell=None, logger=None):
        calls.append(cmd)
        raise pub_mod.CommandError(
            "PR creation failed: body is too long",
            subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="GraphQL: Body is too long (maximum is 65536 characters)",
            ),
        )

    monkeypatch.setattr(pub_mod, "_build_pr_body", lambda issue, repo_root, repo: "short body")
    monkeypatch.setattr(pub_mod, "_find_existing_pr", lambda repo, branch, repo_root: None)
    monkeypatch.setattr(pub_mod, "run_command_or_fail", fake_run_command_or_fail)
    monkeypatch.setattr(pub_mod.time, "sleep", lambda _: None)

    result = _create_pr(REPO, BRANCH, ISSUE, REPO_ROOT)

    assert result is None
    assert len(calls) == 1


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
