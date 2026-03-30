"""Configuration loader."""

from pathlib import Path

import yaml

DEFAULTS = {
    "label": "claude",
    "branch_prefix": "auto/",
    "ai": {
        "provider": "claude-code",
        "model": "sonnet",
        "max_retries": 3,
    },
    "test": {
        "command": "pytest",
        "lint_command": "ruff check .",
    },
    "review": {
        "enabled": True,
        "provider": "claude-code",
    },
    "ci": {
        "enabled": True,
        "timeout": 600,
        "poll_interval": 30,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursing into nested dicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | None = None) -> dict:
    """Load config from YAML file, falling back to defaults."""
    if path is None:
        # Try common locations
        for candidate in ["aiorchestra.yaml", "aiorchestra.yml"]:
            if Path(candidate).exists():
                path = candidate
                break

    if path and Path(path).exists():
        with open(path) as f:
            user_config = yaml.safe_load(f) or {}
        return _deep_merge(DEFAULTS, user_config)

    return DEFAULTS.copy()
