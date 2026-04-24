"""Configuration loader.

Resolution order (each layer merges on top of the previous):
  1. Built-in defaults
  2. Target repo .aiorchestra/config.yaml (if repo_root provided)
  3. Explicit --config path (if provided)
"""

from pathlib import Path

import yaml

DEFAULTS = {
    "ai": {
        "provider": "claude-code",
        "model": "claude-opus-4-6",
        "max_retries": 3,
        "skip_permissions": True,
    },
    "test": {
        "command": "pytest",
        "lint_command": "ruff check .",
    },
    "review": {
        "enabled": True,
        "tiers": [
            {
                "name": "static-analysis",
                "enabled": True,
                "commands": [
                    "semgrep --config=auto --quiet .",
                    "bandit -r . -q",
                ],
            },
            {
                "name": "ai-review",
                "enabled": True,
                "provider": "claude-code",
                "model": "claude-sonnet-4-6",
            },
            {
                "name": "cross-model-review",
                "enabled": False,
                "provider": "ollama",
                "strict": False,
                "ollama": {
                    "endpoint": "http://localhost:11434",
                    "model": "mistral",
                    "timeout": 120,
                },
            },
            {
                "name": "cross-agent-review",
                "enabled": True,
                "provider": "auto",
                "strict": False,
            },
            {
                "name": "human-required",
                "enabled": False,
                "labels": ["security", "breaking-change"],
            },
        ],
    },
    "ci": {
        "enabled": True,
        "timeout": 600,
        "poll_interval": 30,
    },
    "osint": {
        "enabled": False,
        "collectors": [
            "whois",
            "dig",
            "dig-mx",
            "dig-ns",
            "dig-txt",
            "host",
            "http-headers",
        ],
        "targets": [],  # auto-extracted from issue text when empty
        "ollama": {
            "enabled": True,
            "endpoint": "http://localhost:11434",
            "model": "mistral",
            "timeout": 120,
        },
    },
    "sentry": {
        "dsn": "",
        "environment": "production",
        "traces_sample_rate": 0.0,
    },
    "watch": {
        "poll_interval": 300,
    },
}


def _merge_named_lists(base: list[dict], override: list[dict]) -> list:
    """Merge two lists of dicts that each have a ``name`` key.

    Items in *override* update matching items in *base* (by name).
    Override items with no match in *base* are appended.
    Base items with no match in *override* are kept unchanged.
    """
    merged = {item["name"]: dict(item) for item in base}
    for item in override:
        name = item["name"]
        if name in merged:
            merged[name] = _deep_merge(merged[name], item)
        else:
            merged[name] = dict(item)
    # Preserve original ordering from base, then append new entries.
    seen = set()
    result = []
    for item in base:
        name = item["name"]
        if name not in seen:
            result.append(merged[name])
            seen.add(name)
    for item in override:
        if item["name"] not in seen:
            result.append(merged[item["name"]])
            seen.add(item["name"])
    return result


def _is_named_list(value: list) -> bool:
    """Return True if *value* is a list of dicts that all have a ``name`` key."""
    return (
        bool(value) and all(isinstance(v, dict) for v in value) and all("name" in v for v in value)
    )


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursing into nested dicts.

    Lists of dicts with a ``name`` key (e.g. review.tiers) are merged
    by name rather than replaced wholesale.
    """
    result = base.copy()
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        elif isinstance(existing, list) and isinstance(value, list) and _is_named_list(existing):
            result[key] = _merge_named_lists(existing, value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_config(path: str | None = None, repo_root: str | None = None) -> dict:
    """Load config by merging defaults ← repo config ← explicit config."""
    config = DEFAULTS.copy()

    # Layer 2: target repo .aiorchestra/config.yaml
    if repo_root:
        repo_config = Path(repo_root) / ".aiorchestra" / "config.yaml"
        if repo_config.exists():
            config = _deep_merge(config, _load_yaml(repo_config))

    # Layer 3: explicit --config path
    if path is None:
        for candidate in ["aiorchestra.yaml", "aiorchestra.yml"]:
            if Path(candidate).exists():
                path = candidate
                break

    if path and Path(path).exists():
        config = _deep_merge(config, _load_yaml(Path(path)))

    return config
