"""Validate stage — run tests and linters. Pure shell — no AI tokens spent."""

import logging
import subprocess

log = logging.getLogger(__name__)


def validate(config: dict) -> tuple[bool, str | None]:
    """Run tests and linter. Returns (success, error_output)."""
    test_cfg = config.get("test", {})
    errors = []

    # Run linter
    lint_cmd = test_cfg.get("lint_command", "ruff check .")
    log.info("Running linter: %s", lint_cmd)
    result = subprocess.run(lint_cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        errors.append(f"Lint errors:\n{result.stdout}\n{result.stderr}")

    # Run tests
    test_cmd = test_cfg.get("command", "pytest")
    log.info("Running tests: %s", test_cmd)
    result = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        errors.append(f"Test errors:\n{result.stdout}\n{result.stderr}")

    if errors:
        combined = "\n---\n".join(errors)
        log.warning("Validation failed:\n%s", combined)
        return False, combined

    log.info("Validation passed.")
    return True, None
