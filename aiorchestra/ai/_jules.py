"""Google Jules cloud provider (async remote sessions)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

from aiorchestra.ai._base import AIProvider, InvokeResult, _parse_clarification

log = logging.getLogger(__name__)

_JULES_POLL_INTERVAL = 30
_JULES_TIMEOUT = 1800  # 30 minutes


class JulesProvider(AIProvider):
    """Creates a remote Jules session and polls until completion.

    Jules is an asynchronous cloud agent — ``jules remote new`` dispatches work
    and returns a session id.  We poll ``jules remote status`` until the session
    finishes, then pull changes into the local worktree.
    """

    @property
    def _poll_interval(self) -> int:
        return self._config.get("poll_interval", _JULES_POLL_INTERVAL)

    @property
    def _timeout(self) -> int:
        return self._config.get("timeout", _JULES_TIMEOUT)

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        cwd: str | None = None,
    ) -> InvokeResult:
        repo = self._config.get("repo", ".")

        create_cmd = [
            "jules",
            "remote",
            "new",
            "--repo",
            repo,
            "--session",
            prompt,
        ]
        log.info("Creating Jules session for repo=%s...", repo)
        create = subprocess.run(
            create_cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if create.returncode != 0:
            log.error("Jules session creation failed: %s", create.stderr.strip())
            return InvokeResult(success=False, output=create.stderr)

        session_id = create.stdout.strip().splitlines()[-1].strip()
        if not session_id:
            log.error("Jules returned empty session id")
            return InvokeResult(success=False, output="No session id returned")

        log.info("Jules session created: %s", session_id)

        result = self._poll_session(session_id, cwd=cwd)
        if not result.success:
            return result

        return self._pull_changes(session_id, cwd=cwd)

    def _poll_session(self, session_id: str, *, cwd: str | None) -> InvokeResult:
        """Poll ``jules remote status`` until completion or timeout."""
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            status_cmd = ["jules", "remote", "status", session_id]
            status = subprocess.run(
                status_cmd,
                capture_output=True,
                text=True,
                cwd=cwd,
            )
            output = status.stdout.strip().lower()

            if status.returncode != 0:
                log.error("Jules status check failed: %s", status.stderr.strip())
                return InvokeResult(success=False, output=status.stderr)

            if "completed" in output or "done" in output:
                log.info("Jules session completed")
                return InvokeResult(success=True, output=status.stdout)

            if "failed" in output or "error" in output:
                log.error("Jules session failed: %s", status.stdout.strip())
                return InvokeResult(success=False, output=status.stdout)

            log.debug("Jules session still running, polling in %ds...", self._poll_interval)
            time.sleep(self._poll_interval)

        log.error("Jules session timed out after %ds", self._timeout)
        return InvokeResult(success=False, output="Session timed out")

    def _pull_changes(self, session_id: str, *, cwd: str | None) -> InvokeResult:
        """Pull completed session changes into the local worktree."""
        pull_cmd = ["jules", "remote", "pull", session_id]
        log.info("Pulling Jules changes for session %s...", session_id)
        pull = subprocess.run(
            pull_cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if pull.returncode != 0:
            log.error("Jules pull failed: %s", pull.stderr.strip())
            return InvokeResult(success=False, output=pull.stderr)

        return _parse_clarification(pull.stdout)

    def available(self) -> bool:
        return shutil.which("jules") is not None
