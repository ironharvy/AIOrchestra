"""Unified AI provider abstraction.

Every backend (Claude Code CLI, Ollama, …) is an ``AIProvider`` with a single
``run()`` method that accepts a prompt and returns an ``InvokeResult``.  Call
sites no longer need to know *which* backend they talk to — they just call
``create_provider(config).run(prompt, ...)``.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass (moved here from claude.py so it's provider-agnostic)
# ---------------------------------------------------------------------------

# Marker the agent emits when the task description is ambiguous.
_CLARIFICATION_RE = re.compile(
    r"^NEEDS_CLARIFICATION:\s*(.+)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class InvokeResult:
    """Structured outcome of an AI invocation."""

    success: bool
    output: str = ""
    needs_clarification: bool = False
    clarification_message: str = ""


def _parse_clarification(text: str) -> InvokeResult:
    """Check raw agent output for clarification requests."""
    match = _CLARIFICATION_RE.search(text)
    if match:
        return InvokeResult(
            success=True,
            output=text,
            needs_clarification=True,
            clarification_message=match.group(1).strip(),
        )
    return InvokeResult(success=True, output=text)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class AIProvider(ABC):
    """Uniform interface for all AI backends."""

    def __init__(self, config: dict) -> None:
        self._config = config

    @abstractmethod
    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        capture_output: bool = False,
        cwd: str | None = None,
    ) -> InvokeResult:
        """Send *prompt* to the backend and return a structured result."""

    def available(self) -> bool:  # noqa: PLR6301
        """Return True if the backend is reachable.  Override for health-checks."""
        return True


# ---------------------------------------------------------------------------
# Claude Code CLI
# ---------------------------------------------------------------------------


class ClaudeCodeProvider(AIProvider):
    """Invokes the ``claude`` CLI in non-interactive (``--print``) mode."""

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        capture_output: bool = False,
        cwd: str | None = None,
    ) -> InvokeResult:
        cmd: list[str] = ["claude", "--print"]

        skip_perms = self._config.get("skip_permissions", True)
        allowed_tools = self._config.get("allowed_tools")

        if skip_perms:
            cmd.append("--dangerously-skip-permissions")

        if allowed_tools:
            for tool in allowed_tools:
                cmd.extend(["--allowedTools", tool])

        if not skip_perms and not allowed_tools:
            log.error(
                "AI agent has no file-editing permissions — refusing to invoke without tool access"
            )
            return InvokeResult(success=False)

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        log.info("Invoking Claude Code CLI...")
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=cwd,
        )

        if result.returncode != 0:
            log.error("Claude CLI failed: %s", result.stderr.strip())
            return InvokeResult(success=False, output=result.stderr)

        return _parse_clarification(result.stdout)


# ---------------------------------------------------------------------------
# OpenAI Codex CLI
# ---------------------------------------------------------------------------


class CodexProvider(AIProvider):
    """Invokes the ``codex`` CLI in quiet (non-interactive) mode.

    Codex runs locally like Claude Code.  In ``full-auto`` approval mode it
    edits files without interactive confirmation (network is disabled by the
    CLI in this mode).
    """

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        capture_output: bool = False,
        cwd: str | None = None,
    ) -> InvokeResult:
        cmd: list[str] = ["codex", "--quiet"]

        approval = self._config.get("approval_mode", "full-auto")
        cmd.extend(["--approval-mode", approval])

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        cmd.append(prompt)

        log.info("Invoking Codex CLI (approval=%s)...", approval)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
        )

        if result.returncode != 0:
            log.error("Codex CLI failed: %s", result.stderr.strip())
            return InvokeResult(success=False, output=result.stderr)

        return _parse_clarification(result.stdout)

    def available(self) -> bool:
        return shutil.which("codex") is not None


# ---------------------------------------------------------------------------
# Google Gemini CLI
# ---------------------------------------------------------------------------


class GeminiProvider(AIProvider):
    """Invokes the ``gemini`` CLI in headless (``-p``) mode.

    Gemini CLI is Google's local coding agent — the same category as Claude
    Code and Codex.  The ``-p`` flag runs it non-interactively, returning
    text output to stdout.  ``--yolo`` auto-approves tool use (equivalent
    to ``--dangerously-skip-permissions`` for Claude).
    """

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        capture_output: bool = False,
        cwd: str | None = None,
    ) -> InvokeResult:
        cmd: list[str] = ["gemini", "-p"]

        if self._config.get("yolo", True):
            cmd.append("--yolo")

        model = self._config.get("model")
        if model:
            cmd.extend(["-m", model])

        cmd.append(prompt)

        log.info("Invoking Gemini CLI...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
        )

        if result.returncode != 0:
            log.error("Gemini CLI failed: %s", result.stderr.strip())
            return InvokeResult(success=False, output=result.stderr)

        return _parse_clarification(result.stdout)

    def available(self) -> bool:
        return shutil.which("gemini") is not None


# ---------------------------------------------------------------------------
# Google Jules (cloud-based async agent)
# ---------------------------------------------------------------------------

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
        capture_output: bool = False,
        cwd: str | None = None,
    ) -> InvokeResult:
        repo = self._config.get("repo", ".")

        # 1. Create the remote session.
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

        # 2. Poll until the session completes.
        result = self._poll_session(session_id, cwd=cwd)
        if not result.success:
            return result

        # 3. Pull changes into the local worktree.
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


# ---------------------------------------------------------------------------
# Ollama (local LLM via HTTP API)
# ---------------------------------------------------------------------------

_DEFAULT_ENDPOINT = "http://localhost:11434"
_DEFAULT_MODEL = "mistral"
_TIMEOUT_SECONDS = 120


class OllamaProvider(AIProvider):
    """Sends prompts to a local Ollama instance over HTTP."""

    @property
    def _endpoint(self) -> str:
        return self._config.get("endpoint", _DEFAULT_ENDPOINT).rstrip("/")

    @property
    def _model(self) -> str:
        return self._config.get("model", _DEFAULT_MODEL)

    @property
    def _timeout(self) -> int:
        return self._config.get("timeout", _TIMEOUT_SECONDS)

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        capture_output: bool = False,
        cwd: str | None = None,
    ) -> InvokeResult:
        url = f"{self._endpoint}/api/generate"
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        log.info("Invoking Ollama model=%s at %s", self._model, self._endpoint)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310
                data = json.loads(resp.read().decode())
        except urllib.error.URLError as exc:
            log.error("Ollama request failed: %s", exc)
            return InvokeResult(success=False)
        except TimeoutError:
            log.error("Ollama request timed out after %ds", self._timeout)
            return InvokeResult(success=False)

        response_text = data.get("response", "")
        if not response_text:
            log.warning("Ollama returned empty response")
            return InvokeResult(success=False)

        log.debug("Ollama response length: %d chars", len(response_text))
        return InvokeResult(success=True, output=response_text)

    def available(self) -> bool:
        """Quick health check — can we reach the Ollama server?"""
        url = f"{self._endpoint}/api/tags"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
                return resp.status == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# OpenCode CLI
# ---------------------------------------------------------------------------


class OpenCodeProvider(AIProvider):
    """Invokes the ``opencode`` CLI in non-interactive mode.

    OpenCode is a terminal-based AI coding agent.  The ``--print`` flag runs
    it non-interactively, writing the result to stdout.  ``--yes`` auto-approves
    tool use without interactive confirmation.
    """

    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        capture_output: bool = False,
        cwd: str | None = None,
    ) -> InvokeResult:
        cmd: list[str] = ["opencode", "run"]

        if self._config.get("yes", True):
            cmd.append("--yes")

        model = self._config.get("model")
        if model:
            cmd.extend(["--model", model])

        cmd.append(prompt)

        log.info("Invoking OpenCode CLI...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
        )

        if result.returncode != 0:
            log.error("OpenCode CLI failed: %s", result.stderr.strip())
            return InvokeResult(success=False, output=result.stderr)

        return _parse_clarification(result.stdout)

    def available(self) -> bool:
        return shutil.which("opencode") is not None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[AIProvider]] = {
    "claude-code": ClaudeCodeProvider,
    "codex": CodexProvider,
    "gemini": GeminiProvider,
    "jules": JulesProvider,
    "ollama": OllamaProvider,
    "opencode": OpenCodeProvider,
}


def create_provider(config: dict) -> AIProvider:
    """Instantiate the provider specified by ``config["provider"]``.

    The *config* dict is forwarded to the provider constructor, so it can
    contain any backend-specific keys (model, endpoint, timeout, …).
    """
    name = config.get("provider", "claude-code")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown AI provider {name!r}. Available: {', '.join(sorted(_PROVIDERS))}"
        )
    return cls(config)
