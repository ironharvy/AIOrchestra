"""Tests for workspace artifact git handling."""

import subprocess
from pathlib import Path

from aiorchestra.stages._workspace_artifacts import (
    is_workspace_artifact_path,
    publishable_status_paths,
    stage_publishable_changes,
)


def _init_repo(tmp: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=tmp,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AIOrchestra Test"],
        cwd=tmp,
        check=True,
        capture_output=True,
    )


def _run_git(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=tmp,
        check=True,
        capture_output=True,
        text=True,
    )


def _commit_all(tmp: Path, message: str = "commit") -> None:
    _run_git(tmp, "add", "-A")
    _run_git(tmp, "commit", "-m", message)


def _ls_files(tmp: Path) -> str:
    return _run_git(tmp, "ls-files").stdout


def _cached_names(tmp: Path) -> list[str]:
    output = _run_git(tmp, "diff", "--cached", "--name-only").stdout
    return [line for line in output.splitlines() if line]


def test_workspace_artifact_path_filter_matches_nested_artifacts() -> None:
    assert is_workspace_artifact_path(".venv/lib/site.py")
    assert is_workspace_artifact_path("packages/web/node_modules/pkg/index.js")
    assert is_workspace_artifact_path("src/app/__pycache__/x.cpython-312.pyc")
    assert not is_workspace_artifact_path("src/app.py")


def test_stage_publishable_changes_filters_artifacts(tmp_path: Path) -> None:
    """Only source changes should be staged; artifact trees stay untouched."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "real.txt").write_text("ok\n")
    _commit_all(repo)

    (repo / "real.txt").write_text("changed\n")
    vfile = repo / ".venv" / "lib" / "site" / "pkg.py"
    pycache = repo / "app" / "__pycache__" / "x.cpython-312.pyc"
    node_module = repo / "packages" / "web" / "node_modules" / "pkg" / "index.js"
    for path in (vfile, pycache, node_module):
        path.parent.mkdir(parents=True)
        path.write_text("artifact\n")

    staged = stage_publishable_changes(str(repo))

    assert staged == ["real.txt"]
    assert _cached_names(repo) == ["real.txt"]


def test_stage_publishable_changes_stages_deletions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    deleted = repo / "old.txt"
    deleted.write_text("old\n")
    _commit_all(repo)

    deleted.unlink()

    assert stage_publishable_changes(str(repo)) == ["old.txt"]
    assert _run_git(repo, "diff", "--cached", "--name-status").stdout.startswith("D\told.txt")


def test_publishable_status_paths_include_rename_sides(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "old.txt").write_text("old\n")
    _commit_all(repo)

    _run_git(repo, "mv", "old.txt", "new.txt")

    assert set(publishable_status_paths(str(repo))) == {"old.txt", "new.txt"}


def test_stage_publishable_changes_does_not_untrack_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "real.txt").write_text("ok\n")
    artifact = repo / ".venv" / "lib" / "site" / "pkg.py"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("tracked artifact\n")
    _commit_all(repo, "track artifact")

    (repo / "real.txt").write_text("changed\n")
    artifact.write_text("modified artifact\n")

    assert stage_publishable_changes(str(repo)) == ["real.txt"]
    assert _cached_names(repo) == ["real.txt"]
    assert ".venv/lib/site/pkg.py" in _ls_files(repo).splitlines()


def test_stage_publishable_changes_ignores_artifact_only_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    artifact = repo / ".venv" / "lib" / "site" / "pkg.py"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("tracked artifact\n")
    _commit_all(repo, "track artifact")

    artifact.write_text("modified artifact\n")

    assert stage_publishable_changes(str(repo)) == []
    assert _cached_names(repo) == []
    assert ".venv/lib/site/pkg.py" in _ls_files(repo).splitlines()
