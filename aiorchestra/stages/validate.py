"""Validate stage — run tests and linters. Pure shell — no AI tokens spent."""

import logging

from aiorchestra.stages._shell import run_command
from aiorchestra.stages.types import FeedbackResult, PipelineConfig

log = logging.getLogger(__name__)


def validate(config: PipelineConfig, repo_root: str | None = None) -> FeedbackResult:
    """Run tests and linter. Returns (success, error_output)."""
    test_cfg = config.get("test", {})
    errors = []

    # Run linter
    lint_cmd = test_cfg.get("lint_command", "ruff check .")
    log.info("Running linter: %s", lint_cmd)
    result = run_command(
        lint_cmd,
        cwd=repo_root,
        logger=log,
    )
    if result.returncode != 0:
        errors.append(f"Lint errors:\n{result.stdout}\n{result.stderr}")

    # Run tests
    test_cmd = test_cfg.get("command", "pytest")
    log.info("Running tests: %s", test_cmd)
    result = run_command(
        test_cmd,
        cwd=repo_root,
        logger=log,
    )
    if result.returncode != 0:
        errors.append(f"Test errors:\n{result.stdout}\n{result.stderr}")

    if errors:
        combined = "\n---\n".join(errors)
        log.warning("Validation failed:\n%s", combined)
        return False, combined

    log.info("Validation passed.")
    return True, None
