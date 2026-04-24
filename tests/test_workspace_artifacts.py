"""Tests for workspace artifact git handling."""

import subprocess
from pathlib import Path

from aiorchestra.stages._workspace_artifacts import untrack_artifact_paths_from_index


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


def _ls_files(tmp: Path) -> str:
    r = subprocess.run(
        ["git", "ls-files"],
        cwd=tmp,
        check=True,
        capture_output=True,
        text=True,
    )
    return r.stdout


def test_untrack_artifact_paths_removes_venv_from_index(tmp_path: Path) -> None:
    """Orchestrator .venv should not stay in the index after untrack."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "real.txt").write_text("ok\n")
    vfile = repo / ".venv" / "lib" / "site" / "pkg.py"
    vfile.parent.mkdir(parents=True)
    vfile.write_text("# venv file\n")
    subprocess.run(
        ["git", "add", "real.txt", str(vfile.relative_to(repo))],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "commit", "-m", "track venv and real"], cwd=repo, check=True, capture_output=True)
    before = [p for p in _ls_files(repo).splitlines() if p]
    assert any(".venv" in p for p in before), "test setup must include tracked .venv"

    untrack_artifact_paths_from_index(str(repo))
    after = [p for p in _ls_files(repo).splitlines() if p]
    assert "real.txt" in after
    assert not any(".venv" in p for p in after)


def test_untrack_artifact_paths_removes_nested_pycache_from_index(tmp_path: Path) -> None:
    """__pycache__ trees tracked by mistake are dropped from the index."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    pyc = repo / "app" / "__pycache__" / "x.cpython-312.pyc"
    pyc.parent.mkdir(parents=True)
    pyc.write_bytes(b"\x00")
    subprocess.run(["git", "add", "app/"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "pycache"], cwd=repo, check=True, capture_output=True)
    before = [p for p in _ls_files(repo).splitlines() if p]
    assert any("__pycache__" in p for p in before), "test setup must track __pycache__"

    untrack_artifact_paths_from_index(str(repo))
    after = [p for p in _ls_files(repo).splitlines() if p]
    assert not any("__pycache__" in p for p in after)
