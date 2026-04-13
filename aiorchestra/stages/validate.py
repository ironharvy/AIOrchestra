"""Validate stage — run tests, linters, and static analysis. Pure shell — no AI tokens spent."""

import logging
import shutil

from aiorchestra.stages._shell import StageTimer, run_command
from aiorchestra.stages.types import FeedbackResult, PipelineConfig

log = logging.getLogger(__name__)


def _run_static_analysis(
    review_cfg: PipelineConfig,
    repo_root: str | None = None,
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

    # T0: Linter
    lint_cmd = test_cfg.get("lint_command", "ruff check .")
    log.info("Running linter: %s", lint_cmd)
    with timer.step("lint"):
        result = run_command(lint_cmd, cwd=repo_root, logger=log)
        if result.returncode != 0:
            errors.append(f"Lint errors:\n{result.stdout}\n{result.stderr}")

    # T0: Tests
    test_cmd = test_cfg.get("command", "pytest")
    log.info("Running tests: %s", test_cmd)
    with timer.step("tests"):
        result = run_command(test_cmd, cwd=repo_root, logger=log)
        if result.returncode != 0:
            errors.append(f"Test errors:\n{result.stdout}\n{result.stderr}")

    # T1: Static analysis (semgrep, bandit, etc.)
    errors.extend(_run_static_analysis(review_cfg, repo_root))

    log.info("[validate] completed in %.1fs (%s)", timer.total, timer.summary())

    if errors:
        combined = "\n---\n".join(errors)
        log.warning("Validation failed:\n%s", combined)
        return False, combined

    log.info("Validation passed.")
    return True, None
