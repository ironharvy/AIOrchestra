"""Provider registry and factory function."""

from __future__ import annotations

from aiorchestra.ai._base import AIProvider
from aiorchestra.ai._claude_code import ClaudeCodeProvider
from aiorchestra.ai._codex import CodexProvider
from aiorchestra.ai._gemini import GeminiProvider
from aiorchestra.ai._jules import JulesProvider
from aiorchestra.ai._ollama import OllamaProvider
from aiorchestra.ai._opencode import OpenCodeProvider

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
    contain any backend-specific keys (model, endpoint, timeout, ...).
    """
    name = config.get("provider", "claude-code")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown AI provider {name!r}. Available: {', '.join(sorted(_PROVIDERS))}"
        )
    return cls(config)
