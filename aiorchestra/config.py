"""Configuration loader.

Resolution order (each layer merges on top of the previous):
  1. Built-in defaults
  2. Target repo .aiorchestra/config.yaml (if repo_root provided)
  3. Explicit --config path (if provided)
"""

from pathlib import Path

import yaml

DEFAULTS = {
    "label": "claude",
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
