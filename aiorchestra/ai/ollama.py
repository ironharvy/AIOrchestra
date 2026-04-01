"""Ollama provider — local LLM inference via the Ollama HTTP API."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "http://localhost:11434"
_DEFAULT_MODEL = "mistral"
_TIMEOUT_SECONDS = 120


def invoke_ollama(
    prompt: str,
    ollama_config: dict,
    system: str | None = None,
) -> str | None:
    """Send a prompt to Ollama and return the response text.

    Returns ``None`` on failure so callers can degrade gracefully.
    """
    endpoint = ollama_config.get("endpoint", _DEFAULT_ENDPOINT).rstrip("/")
    model = ollama_config.get("model", _DEFAULT_MODEL)
    timeout = ollama_config.get("timeout", _TIMEOUT_SECONDS)

    url = f"{endpoint}/api/generate"
    payload: dict = {
        "model": model,
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

    log.info("Invoking Ollama model=%s at %s", model, endpoint)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        log.error("Ollama request failed: %s", exc)
        return None
    except TimeoutError:
        log.error("Ollama request timed out after %ds", timeout)
        return None

    response_text = data.get("response", "")
    if not response_text:
        log.warning("Ollama returned empty response")
        return None

    log.debug("Ollama response length: %d chars", len(response_text))
    return response_text


def ollama_available(ollama_config: dict) -> bool:
    """Quick health check — can we reach the Ollama server?"""
    endpoint = ollama_config.get("endpoint", _DEFAULT_ENDPOINT).rstrip("/")
    url = f"{endpoint}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False
