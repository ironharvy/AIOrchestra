"""Tests for prepare-stage workspace hygiene."""

from aiorchestra.stages._workspace_artifacts import (
    LOCAL_GIT_EXCLUDE_PATTERNS,
    ensure_local_git_excludes,
)


def test_ensure_local_git_excludes_adds_patterns_once(tmp_path):
    """Workspace-local excludes should be appended without duplication."""
    repo_dir = tmp_path / "repo"
    exclude_file = repo_dir / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True)
    exclude_file.write_text("*.log\n", encoding="utf-8")

    ensure_local_git_excludes(repo_dir)
    ensure_local_git_excludes(repo_dir)

    content = exclude_file.read_text(encoding="utf-8")
    lines = content.splitlines()

    assert "*.log\n" in content
    assert content.count("# AIOrchestra local workspace excludes\n") == 1
    for pattern in LOCAL_GIT_EXCLUDE_PATTERNS:
        assert lines.count(pattern) == 1
