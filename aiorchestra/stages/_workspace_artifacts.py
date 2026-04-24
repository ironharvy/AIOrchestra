"""Workspace paths that the orchestrator creates and must not land in agent commits.

Local `.git/info/exclude` keeps them untracked. If they were ever staged or
tracked, `untrack_artifact_paths` removes them from the index before publish.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiorchestra.stages._shell import run_command

log = logging.getLogger(__name__)

# Used in `.git/info/exclude` and for display — trailing slash for ignore patterns
LOCAL_GIT_EXCLUDE_PATTERNS = (
    ".venv/",
    "venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".tox/",
    "node_modules/",
)

# Top-level (or well-known) paths passed to `git rm -r --cached` — no trailing slash
_GIT_RM_TOP_LEVEL = (
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
)


def ensure_local_git_excludes(repo_dir: Path) -> None:
    """Append orchestrator ignore patterns to `.git/info/exclude` (idempotent)."""
    exclude_file = repo_dir / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)

    existing_text = ""
    if exclude_file.exists():
        existing_text = exclude_file.read_text(encoding="utf-8")

    existing_entries = {line.strip() for line in existing_text.splitlines() if line.strip()}
    missing = [p for p in LOCAL_GIT_EXCLUDE_PATTERNS if p not in existing_entries]
    if not missing:
        return

    with exclude_file.open("a", encoding="utf-8") as handle:
        if existing_text and not existing_text.endswith("\n"):
            handle.write("\n")
        handle.write("# AIOrchestra local workspace excludes\n")
        for pattern in missing:
            handle.write(f"{pattern}\n")

    log.info("Added %d local git exclude patterns in %s", len(missing), exclude_file)


def _pycache_dirs_in_index(repo_root: str) -> set[str]:
    result = run_command(
        ["git", "ls-files"],
        cwd=repo_root,
        logger=log,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return set()
    dirs: set[str] = set()
    for path in result.stdout.splitlines():
        if "__pycache__" not in path:
            continue
        parts = path.split("/")
        for i, segment in enumerate(parts):
            if segment == "__pycache__":
                dirs.add("/".join(parts[: i + 1]))
    return dirs


def _untrack_pycache_paths(repo_root: str) -> None:
    for d in sorted(_pycache_dirs_in_index(repo_root)):
        run_command(
            ["git", "rm", "-r", "--cached", "--ignore-unmatch", "--", d],
            cwd=repo_root,
            check=False,
            logger=log,
        )


def untrack_artifact_paths_from_index(repo_root: str) -> None:
    """Remove orchestration artifacts from the git index; leaves working tree on disk.

    Call this before `git add -A` so venv, caches, and `__pycache__` never
    become part of the commit. Untracked copies stay ignored via
    :func:`ensure_local_git_excludes`.
    """
    for name in _GIT_RM_TOP_LEVEL:
        run_command(
            ["git", "rm", "-r", "--cached", "--ignore-unmatch", "--", name],
            cwd=repo_root,
            check=False,
            logger=log,
        )
    _untrack_pycache_paths(repo_root)
