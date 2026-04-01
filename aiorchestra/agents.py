"""Helpers for normalizing provider ids into agent-family names."""

from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_AGENT_FAMILY = "claude"
KNOWN_AGENTS: tuple[str, ...] = ("claude", "codex", "jules")


def normalize_agent_family(value: str | None) -> str:
    """Collapse provider ids like ``claude-code`` into ``claude``."""
    if not value:
        return DEFAULT_AGENT_FAMILY

    normalized = value.strip().lower()
    if not normalized:
        return DEFAULT_AGENT_FAMILY

    for family in ("claude", "codex"):
        if family in normalized:
            return family

    for separator in ("-", "_", "/", " "):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0]
            break

    return normalized or DEFAULT_AGENT_FAMILY


def agent_family_from_config(config: Mapping[str, Any]) -> str:
    """Resolve the current agent family from configuration."""
    ai_config = config.get("ai", {})
    provider = ai_config.get("provider") if isinstance(ai_config, Mapping) else None
    fallback = config.get("label")
    return normalize_agent_family(provider or fallback)


def build_agent_branch(config: Mapping[str, Any], issue_number: int) -> str:
    """Build a branch name from the configured agent family."""
    return f"{agent_family_from_config(config)}/{issue_number}"


def resolve_agent(
    issue_labels: Sequence[str],
    default: str = DEFAULT_AGENT_FAMILY,
) -> str:
    """Pick the agent family from *issue_labels*, or fall back to *default*.

    Scans labels for a known agent name (claude, codex, jules).  The first
    match wins.  If no label matches, returns *default*.
    """
    for label in issue_labels:
        normalized = label.strip().lower()
        for agent in KNOWN_AGENTS:
            if agent in normalized:
                return agent
    return default
