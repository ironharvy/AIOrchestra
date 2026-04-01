"""CI watch stage — poll for CI completion. Pure shell — no AI tokens spent."""

import json
import logging
import time

from aiorchestra.stages._shell import run_command
from aiorchestra.stages.types import FeedbackResult, PipelineConfig

log = logging.getLogger(__name__)

_CI_FIELDS = "name,state,bucket,link,workflow"


def wait_for_ci(pr_url: str, config: PipelineConfig) -> FeedbackResult:
    """Poll CI status until completion. Returns (success, failure_output)."""
    ci_cfg = config.get("ci", {})
    timeout = ci_cfg.get("timeout", 600)
    poll_interval = ci_cfg.get("poll_interval", 30)

    deadline = time.monotonic() + timeout
    log.info("Waiting for CI (timeout=%ds)...", timeout)

    while time.monotonic() < deadline:
        result = run_command(
            ["gh", "pr", "checks", pr_url, "--json", _CI_FIELDS],
            logger=log,
        )
        if result.returncode != 0:
            log.warning("Failed to check CI status: %s", result.stderr.strip())
            time.sleep(poll_interval)
            continue

        checks = json.loads(result.stdout)

        if not checks:
            time.sleep(poll_interval)
            continue

        all_done = all(c.get("bucket") != "pending" for c in checks)
        if not all_done:
            pending = [c["name"] for c in checks if c.get("bucket") == "pending"]
            log.debug("Still pending: %s", ", ".join(pending))
            time.sleep(poll_interval)
            continue

        all_passed = all(c.get("bucket") == "pass" for c in checks)
        if all_passed:
            log.info("CI passed.")
            return True, None

        failures = [c for c in checks if c.get("bucket") == "fail"]
        summary = "\n".join(
            f"- {c['name']}: {c.get('state', 'unknown')} ({c.get('link', '')})" for c in failures
        )
        log.warning("CI failed:\n%s", summary)

        log_output = _fetch_failure_logs(pr_url)
        return False, f"CI failures:\n{summary}\n\n{log_output}"

    log.error("CI timed out after %ds", timeout)
    return False, "CI timed out."


def _fetch_failure_logs(pr_url: str) -> str:
    """Best-effort fetch of CI failure logs."""
    result = run_command(["gh", "pr", "checks", pr_url, "--fail-fast"], logger=log)
    return result.stdout + result.stderr
