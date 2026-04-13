"""AI provider package — Strategy pattern for multi-backend orchestration.

Public API::

    from aiorchestra.ai import AIProvider, InvokeResult, create_provider
"""

from aiorchestra.ai._agents import (
    DEFAULT_AGENT_FAMILY,
    KNOWN_AGENTS,
    agent_family_from_config,
    build_agent_branch,
    normalize_agent_family,
    provider_for_agent,
    resolve_agent,
)
from aiorchestra.ai._base import AIProvider, InvokeResult, _parse_clarification
from aiorchestra.ai._claude_code import ClaudeCodeProvider
from aiorchestra.ai._cli import CLIProvider
from aiorchestra.ai._codex import CodexProvider
from aiorchestra.ai._gemini import GeminiProvider
from aiorchestra.ai._jules import JulesProvider
from aiorchestra.ai._ollama import OllamaProvider
from aiorchestra.ai._opencode import OpenCodeProvider
from aiorchestra.ai._registry import create_provider

__all__ = [
    "AIProvider",
    "CLIProvider",
    "ClaudeCodeProvider",
    "CodexProvider",
    "DEFAULT_AGENT_FAMILY",
    "GeminiProvider",
    "InvokeResult",
    "JulesProvider",
    "KNOWN_AGENTS",
    "OllamaProvider",
    "OpenCodeProvider",
    "_parse_clarification",
    "agent_family_from_config",
    "build_agent_branch",
    "create_provider",
    "normalize_agent_family",
    "provider_for_agent",
    "resolve_agent",
]
