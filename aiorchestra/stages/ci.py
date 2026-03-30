"""CI watch stage — poll for CI completion. Pure shell — no AI tokens spent."""

import logging
import subprocess
import time

log = logging.getLogger(__name__)


def wait_for_ci(pr_url: str, config: dict) -> tuple[bool, str | None]:
    """Poll CI status until completion. Returns (success, failure_output)."""
    ci_cfg = config.get("ci", {})
    timeout = ci_cfg.get("timeout", 600)
    poll_interval = ci_cfg.get("poll_interval", 30)

    deadline = time.monotonic() + timeout
    log.info("Waiting for CI (timeout=%ds)...", timeout)

    while time.monotonic() < deadline:
        result = subprocess.run(
            ["gh", "pr", "checks", pr_url, "--json", "name,state,conclusion"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.warning("Failed to check CI status: %s", result.stderr.strip())
            time.sleep(poll_interval)
            continue

        import json
        checks = json.loads(result.stdout)

        if not checks:
            time.sleep(poll_interval)
            continue

        all_done = all(c.get("state") == "COMPLETED" for c in checks)
        if not all_done:
            time.sleep(poll_interval)
            continue

        all_passed = all(c.get("conclusion") == "SUCCESS" for c in checks)
        if all_passed:
            log.info("CI passed.")
            return True, None

        # Collect failure details
        failures = [c for c in checks if c.get("conclusion") != "SUCCESS"]
        summary = "\n".join(f"- {c['name']}: {c.get('conclusion', 'unknown')}" for c in failures)
        log.warning("CI failed:\n%s", summary)

        # Try to get logs from failed runs
        log_output = _fetch_failure_logs(pr_url)
        return False, f"CI failures:\n{summary}\n\n{log_output}"

    log.error("CI timed out after %ds", timeout)
    return False, "CI timed out."


def _fetch_failure_logs(pr_url: str) -> str:
    """Best-effort fetch of CI failure logs."""
    result = subprocess.run(
        ["gh", "pr", "checks", pr_url, "--fail-fast"],
        capture_output=True, text=True,
    )
    return result.stdout + result.stderr
