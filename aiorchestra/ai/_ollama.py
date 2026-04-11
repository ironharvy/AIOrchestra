"""Ollama local LLM provider (HTTP API)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from aiorchestra.ai._base import AIProvider, InvokeResult, _parse_clarification

log = logging.getLogger(__name__)

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
        return _parse_clarification(response_text)

    def available(self) -> bool:
        """Quick health check — can we reach the Ollama server?"""
        url = f"{self._endpoint}/api/tags"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
                return resp.status == 200
        except Exception:
            return False
