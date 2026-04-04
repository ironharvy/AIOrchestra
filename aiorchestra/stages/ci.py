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

    ci_start = time.monotonic()
    deadline = ci_start + timeout
    poll_count = 0
    log.info("Waiting for CI (timeout=%ds)...", timeout)

    while time.monotonic() < deadline:
        result = run_command(
            ["gh", "pr", "checks", pr_url, "--json", _CI_FIELDS],
            logger=log,
        )
        poll_count += 1
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

        elapsed = time.monotonic() - ci_start
        all_passed = all(c.get("bucket") == "pass" for c in checks)
        if all_passed:
            log.info("[ci] completed in %.1fs (%d polls)", elapsed, poll_count)
            log.info("CI passed.")
            return True, None

        failures = [c for c in checks if c.get("bucket") == "fail"]
        summary = "\n".join(
            f"- {c['name']}: {c.get('state', 'unknown')} ({c.get('link', '')})" for c in failures
        )
        log.warning("CI failed:\n%s", summary)
        log.info("[ci] completed in %.1fs (%d polls)", elapsed, poll_count)

        log_output = _fetch_failure_logs(pr_url)
        if log_output:
            preview = "\n".join(log_output.splitlines()[:20])
            log.info("CI failure output (first 20 lines):\n%s", preview)
            log.debug("CI failure full output:\n%s", log_output)
        return False, f"CI failures:\n{summary}\n\n{log_output}"

    elapsed = time.monotonic() - ci_start
    log.info("[ci] completed in %.1fs (%d polls)", elapsed, poll_count)
    log.error("CI timed out after %ds", timeout)
    return False, "CI timed out."


def _fetch_failure_logs(pr_url: str) -> str:
    """Best-effort fetch of CI failure logs."""
    result = run_command(
        ["gh", "pr", "checks", pr_url, "--json", "name,link,state,bucket"],
        logger=log,
    )
    if result.returncode != 0:
        return ""
    try:
        checks = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return ""

    failures = [c for c in checks if c.get("bucket") == "fail"]
    if not failures:
        return ""

    logs = []
    seen_runs: set[str] = set()
    for check in failures:
        link = check.get("link", "")
        if "/job/" in link:
            run_url = link.split("/job/")[0]
        elif "/runs/" in link:
            run_url = link
        else:
            run_url = ""
        if run_url and run_url not in seen_runs:
            seen_runs.add(run_url)
            log_result = run_command(
                ["gh", "run", "view", run_url, "--log-failed"],
                logger=log,
            )
            if log_result.returncode == 0:
                logs.append(log_result.stdout)
    return "\n---\n".join(logs) if logs else ""
