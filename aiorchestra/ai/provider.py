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
import subprocess
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
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
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
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[AIProvider]] = {
    "claude-code": ClaudeCodeProvider,
    "ollama": OllamaProvider,
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
