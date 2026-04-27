"""Workspace paths that the orchestrator creates and must not land in agent commits.

Local `.git/info/exclude` keeps untracked copies out of status. Publish uses
filtered path staging so the orchestrator does not forcibly remove target-repo
paths that happen to match common artifact names.
"""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath

from aiorchestra.stages._shell import CommandError, run_command, run_command_or_fail

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

_ARTIFACT_DIR_NAMES = frozenset(pattern.rstrip("/") for pattern in LOCAL_GIT_EXCLUDE_PATTERNS)


class GitStatusError(RuntimeError):
    """Raised when git status/add cannot be inspected safely."""


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


def _status_paths_from_porcelain_z(output: str) -> list[str]:
    """Return all paths mentioned by `git status --porcelain -z`.

    Rename/copy records contain two NUL-delimited paths. We keep both so
    `git add -A -- <paths>` can stage the old deletion and the new path.
    """
    entries = output.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        if len(entry) < 4:
            continue

        status = entry[:2]
        path = entry[3:]
        if path:
            paths.append(path)

        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            if i < len(entries) and entries[i]:
                paths.append(entries[i])
            i += 1

    return paths


def is_workspace_artifact_path(path: str) -> bool:
    """Return True when *path* lives under an orchestrator-created artifact dir."""
    return any(part in _ARTIFACT_DIR_NAMES for part in PurePosixPath(path).parts)


def publishable_status_paths(repo_root: str) -> list[str]:
    """Return dirty worktree paths that are safe to include in an agent commit."""
    try:
        result = run_command_or_fail(
            ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
            error_msg="Failed to inspect git status",
            cwd=repo_root,
            logger=log,
        )
    except CommandError as exc:
        raise GitStatusError(str(exc)) from exc

    paths = _status_paths_from_porcelain_z(result.stdout)
    publishable = [path for path in paths if not is_workspace_artifact_path(path)]
    return list(dict.fromkeys(publishable))


def has_publishable_changes(repo_root: str) -> bool:
    """Return True if the worktree has non-artifact changes."""
    return bool(publishable_status_paths(repo_root))


def stage_publishable_changes(repo_root: str) -> list[str]:
    """Stage only non-artifact dirty paths.

    Returns the paths that have staged changes after filtering.
    """
    paths = publishable_status_paths(repo_root)
    if not paths:
        log.debug("No publishable local changes to stage.")
        return []

    try:
        run_command_or_fail(
            ["git", "add", "-A", "--", *paths],
            error_msg="git add failed",
            cwd=repo_root,
            logger=log,
        )
        diff = run_command(
            ["git", "diff", "--cached", "--quiet", "--", *paths],
            cwd=repo_root,
            logger=log,
        )
    except CommandError as exc:
        raise GitStatusError(str(exc)) from exc

    if diff.returncode not in {0, 1}:
        detail = diff.stderr.strip() or diff.stdout.strip() or "git diff failed"
        raise GitStatusError(f"Failed to inspect staged diff: {detail}")

    if diff.returncode == 0:
        return []
    return paths
