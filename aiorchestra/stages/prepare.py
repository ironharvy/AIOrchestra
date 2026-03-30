"""Prepare the working environment. Pure shell — no AI tokens spent."""

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_WORKSPACE = Path.home() / ".aiorchestra" / "workspaces"


def _run(cmd: list[str], check: bool = True, cwd: str | None = None) -> subprocess.CompletedProcess:
    log.info("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=check, cwd=cwd)


def prepare_environment(repo: str, branch: str, workspace: str | None = None) -> str | None:
    """Clone (if needed), pull latest, create branch.

    Args:
        repo: GitHub repo in "owner/repo" format.
        branch: Branch name to create.
        workspace: Root directory for cloned repos. Defaults to ~/.aiorchestra/workspaces.

    Returns:
        Path to the repo working directory, or None on failure.
    """
    workspace_root = Path(workspace) if workspace else DEFAULT_WORKSPACE
    repo_name = repo.split("/")[-1]
    repo_dir = workspace_root / repo_name

    try:
        # Clone if the repo dir doesn't exist
        if not (repo_dir / ".git").exists():
            log.info("Cloning %s into %s", repo, repo_dir)
            repo_dir.mkdir(parents=True, exist_ok=True)
            _run(
                ["gh", "repo", "clone", repo, str(repo_dir)],
            )
        else:
            log.info("Repo already cloned at %s", repo_dir)

        # Fetch latest and create branch
        _run(["git", "fetch", "origin"], cwd=str(repo_dir))

        # Try to create branch; if it exists, just check it out
        result = _run(
            ["git", "checkout", "-b", branch, "origin/main"],
            check=False, cwd=str(repo_dir),
        )
        if result.returncode != 0:
            log.info("Branch may exist, trying checkout: %s", branch)
            _run(["git", "checkout", branch], cwd=str(repo_dir))
            _run(["git", "merge", "origin/main", "--no-edit"], check=False, cwd=str(repo_dir))

        # Install deps if common files exist
        _install_deps(repo_dir)

        return str(repo_dir)

    except subprocess.CalledProcessError as exc:
        log.error("Prepare failed: %s", exc.stderr)
        return None


def _install_deps(repo_dir: Path) -> None:
    """Best-effort dependency installation."""
    cwd = str(repo_dir)

    if (repo_dir / "requirements.txt").exists():
        log.info("Installing from requirements.txt")
        _run(["pip", "install", "-r", "requirements.txt"], check=False, cwd=cwd)
    elif (repo_dir / "pyproject.toml").exists():
        log.info("Installing from pyproject.toml")
        _run(["pip", "install", "-e", "."], check=False, cwd=cwd)
    elif (repo_dir / "setup.py").exists():
        log.info("Installing from setup.py")
        _run(["pip", "install", "-e", "."], check=False, cwd=cwd)
