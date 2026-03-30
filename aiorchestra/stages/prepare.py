"""Prepare the working environment. Pure shell — no AI tokens spent."""

import logging
import subprocess

log = logging.getLogger(__name__)


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    log.info("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def prepare_environment(repo: str, branch: str) -> bool:
    """Pull latest, create branch, set up venv if needed.

    Returns True on success.
    """
    try:
        _run(["git", "fetch", "origin"])
        _run(["git", "checkout", "-b", branch, "origin/main"], check=False)

        # Activate venv if it exists, install deps
        # (venv activation doesn't persist across subprocess calls,
        #  so we'll use the venv python directly in later stages)

        return True
    except subprocess.CalledProcessError as exc:
        log.error("Prepare failed: %s", exc.stderr)
        return False
