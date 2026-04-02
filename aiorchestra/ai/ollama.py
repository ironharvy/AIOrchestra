"""Ollama provider — backward-compatibility shim.

The canonical implementation now lives in :mod:`aiorchestra.ai.provider`
(``OllamaProvider``).  This module re-exports helpers that existing call-sites
and tests import so nothing breaks.
"""

from __future__ import annotations

from aiorchestra.ai.provider import OllamaProvider, create_provider

__all__ = ["invoke_ollama", "ollama_available"]


def invoke_ollama(
    prompt: str,
    ollama_config: dict,
    system: str | None = None,
) -> str | None:
    """Send a prompt to Ollama and return the response text.

    Returns ``None`` on failure so callers can degrade gracefully.

    Thin wrapper kept for backward compatibility — delegates to
    ``OllamaProvider.run()``.
    """
    provider = create_provider({**ollama_config, "provider": "ollama"})
    result = provider.run(prompt, system=system)
    return result.output if result.success else None


def ollama_available(ollama_config: dict) -> bool:
    """Quick health check — can we reach the Ollama server?"""
    provider = OllamaProvider(ollama_config)
    return provider.available()
