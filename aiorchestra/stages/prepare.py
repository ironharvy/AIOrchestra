"""Prepare the working environment. Pure shell — no AI tokens spent."""

import logging
import os
import sys
from pathlib import Path

from aiorchestra.stages._shell import run_command

log = logging.getLogger(__name__)

DEFAULT_WORKSPACE = Path.home() / ".aiorchestra" / "workspaces"


def prepare_environment(repo: str, branch: str, workspace: str | None = None) -> str | None:
    """Clone (if needed), create venv, install deps.

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
        # -- Phase 1: Git ------------------------------------------------
        _setup_git(repo, branch, repo_dir)

        # -- Phase 2: Virtual environment ---------------------------------
        _setup_venv(repo_dir)

        # -- Phase 3: Dependencies ----------------------------------------
        _install_deps(repo_dir)

        return str(repo_dir)

    except RuntimeError as exc:
        log.error("Prepare failed: %s", exc)
        return None


def _setup_git(repo: str, branch: str, repo_dir: Path) -> None:
    """Clone if needed, fetch latest, create or checkout branch."""
    cwd = str(repo_dir)

    if not (repo_dir / ".git").exists():
        log.info("Cloning %s into %s", repo, repo_dir)
        repo_dir.mkdir(parents=True, exist_ok=True)
        _require_success(run_command(["gh", "repo", "clone", repo, cwd], logger=log))
    else:
        log.info("Repo already cloned at %s", repo_dir)

    _require_success(run_command(["git", "fetch", "origin"], cwd=cwd, logger=log))

    result = run_command(
        ["git", "checkout", "-b", branch, "origin/main"],
        check=False,
        cwd=cwd,
        logger=log,
    )
    if result.returncode != 0:
        log.info("Branch may exist, trying checkout: %s", branch)
        _require_success(run_command(["git", "checkout", branch], cwd=cwd, logger=log))
        run_command(
            ["git", "merge", "origin/main", "--no-edit"],
            check=False,
            cwd=cwd,
            logger=log,
        )


def _setup_venv(repo_dir: Path) -> None:
    """Create a .venv inside repo_dir (if missing) and prepend it to PATH."""
    venv_dir = repo_dir / ".venv"

    if not (venv_dir / "bin" / "python").exists():
        log.info("Creating virtual environment at %s", venv_dir)
        _require_success(run_command([sys.executable, "-m", "venv", str(venv_dir)], logger=log))
    else:
        log.info("Virtual environment already exists at %s", venv_dir)

    venv_bin = str(venv_dir / "bin")
    os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")
    log.info("PATH updated: %s prepended", venv_bin)


def _install_deps(repo_dir: Path) -> None:
    """Install project deps then mandatory tooling (pytest, ruff)."""
    cwd = str(repo_dir)

    run_command(
        ["python", "-m", "pip", "install", "--upgrade", "pip"],
        check=False,
        cwd=cwd,
        logger=log,
    )

    if (repo_dir / "requirements.txt").exists():
        log.info("Installing from requirements.txt")
        run_command(["pip", "install", "-r", "requirements.txt"], check=False, cwd=cwd, logger=log)
    elif (repo_dir / "pyproject.toml").exists():
        log.info("Installing from pyproject.toml")
        run_command(["pip", "install", "-e", "."], check=False, cwd=cwd, logger=log)
    elif (repo_dir / "setup.py").exists():
        log.info("Installing from setup.py")
        run_command(["pip", "install", "-e", "."], check=False, cwd=cwd, logger=log)

    run_command(["pip", "install", "pytest", "ruff"], check=False, cwd=cwd, logger=log)


def _require_success(result) -> None:
    if result.returncode == 0:
        return

    error = result.stderr.strip() or result.stdout.strip() or "command failed"
    raise RuntimeError(error)
