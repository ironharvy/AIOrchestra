"""Validate stage — run tests, linters, and static analysis. Pure shell — no AI tokens spent."""

import logging
import shutil
from pathlib import Path

from aiorchestra.stages._shell import StageTimer, run_command
from aiorchestra.stages.types import FeedbackResult, PipelineConfig

log = logging.getLogger(__name__)

# Directories to skip when probing for project source files. Mirrors the
# default excludes wired into the static-analysis commands.
_IGNORED_DIRS = {".venv", "venv", ".git", "node_modules", "__pycache__", ".tox"}

# pytest exit code 5 == "no tests were collected" — not a real failure for
# projects that simply don't have tests (e.g. a static site).
_PYTEST_NO_TESTS_COLLECTED = 5

# Python-centric tools that only make sense when the repo has *.py sources.
_PYTHON_ONLY_TOOLS = frozenset({"ruff", "pytest", "mypy", "bandit", "pyright", "pylint"})


def _has_python_sources(repo_root: str | None) -> bool:
    """Return True if *repo_root* contains any tracked ``*.py`` file.

    Walks the tree but ignores venvs, VCS metadata, caches, and node_modules
    so a stray `.venv/` from `_setup_venv` doesn't make a static-only repo
    look like a Python project.
    """
    if not repo_root:
        return True  # Be permissive when no root is given (legacy callers).

    root = Path(repo_root)
    if not root.exists():
        return True

    for path in root.rglob("*.py"):
        if any(part in _IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        return True
    return False


def _is_python_tool(cmd: str) -> bool:
    tool = cmd.split(maxsplit=1)[0] if cmd else ""
    return tool in _PYTHON_ONLY_TOOLS


def _run_static_analysis(
    review_cfg: PipelineConfig,
    repo_root: str | None = None,
    *,
    python_project: bool = True,
) -> list[str]:
    """Run static-analysis tier commands (T1). Returns list of error strings."""
    tiers = review_cfg.get("tiers", [])
    sa_tier = next((t for t in tiers if t.get("name") == "static-analysis"), None)
    if not sa_tier or not sa_tier.get("enabled", False):
        return []

    errors = []
    for cmd in sa_tier.get("commands", []):
        tool_name = cmd.split()[0]
        if not shutil.which(tool_name):
            log.info("Static analysis tool '%s' not found on PATH, skipping", tool_name)
            continue

        if not python_project and _is_python_tool(cmd):
            log.info("Skipping %s — repo has no Python sources", tool_name)
            continue

        log.info("Running static analysis: %s", cmd)
        result = run_command(cmd, cwd=repo_root, logger=log)
        if result.returncode != 0:
            errors.append(f"Static analysis ({tool_name}):\n{result.stdout}\n{result.stderr}")

    return errors


def validate(config: PipelineConfig, repo_root: str | None = None) -> FeedbackResult:
    """Run tests, linter, and static analysis. Returns (success, error_output)."""
    timer = StageTimer()
    test_cfg = config.get("test", {})
    review_cfg = config.get("review", {})
    errors = []

    python_project = _has_python_sources(repo_root)
    if not python_project:
        log.info("No Python sources detected — skipping ruff/pytest/bandit/etc.")

    # T0: Linter
    lint_cmd = test_cfg.get("lint_command", "ruff check .")
    if python_project or not _is_python_tool(lint_cmd):
        log.info("Running linter: %s", lint_cmd)
        with timer.step("lint"):
            result = run_command(lint_cmd, cwd=repo_root, logger=log)
            if result.returncode != 0:
                errors.append(f"Lint errors:\n{result.stdout}\n{result.stderr}")

    # T0: Tests
    test_cmd = test_cfg.get("command", "pytest")
    if python_project or not _is_python_tool(test_cmd):
        log.info("Running tests: %s", test_cmd)
        with timer.step("tests"):
            result = run_command(test_cmd, cwd=repo_root, logger=log)
            # pytest returns 5 when no tests were collected; treat that as a
            # pass so repos without a test suite don't trip validation.
            is_pytest = test_cmd.split(maxsplit=1)[0] == "pytest"
            ok = result.returncode == 0 or (
                is_pytest and result.returncode == _PYTEST_NO_TESTS_COLLECTED
            )
            if not ok:
                errors.append(f"Test errors:\n{result.stdout}\n{result.stderr}")
            elif is_pytest and result.returncode == _PYTEST_NO_TESTS_COLLECTED:
                log.info("pytest collected no tests — treating as pass")

    # T1: Static analysis (semgrep, bandit, etc.)
    errors.extend(_run_static_analysis(review_cfg, repo_root, python_project=python_project))

    log.info("[validate] completed in %.1fs (%s)", timer.total, timer.summary())

    if errors:
        combined = "\n---\n".join(errors)
        log.warning("Validation failed:\n%s", combined)
        return False, combined

    log.info("Validation passed.")
    return True, None
