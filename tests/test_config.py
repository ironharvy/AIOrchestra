"""Tests for config loading."""

from aiorchestra.config import load_config, _deep_merge, _merge_named_lists


def test_defaults_returned_when_no_file():
    config = load_config("/nonexistent/path.yaml")
    assert config["label"] == "claude"
    assert config["ai"]["max_retries"] == 3
    assert "branch_prefix" not in config


def test_deep_merge():
    base = {"a": 1, "nested": {"x": 10, "y": 20}}
    override = {"a": 2, "nested": {"y": 99}}
    result = _deep_merge(base, override)
    assert result == {"a": 2, "nested": {"x": 10, "y": 99}}


def test_deep_merge_named_lists():
    """Enabling one tier should not wipe out other tiers."""
    base = {
        "tiers": [
            {"name": "static-analysis", "enabled": False, "commands": ["semgrep ."]},
            {"name": "ai-review", "enabled": True, "provider": "claude-code"},
        ]
    }
    override = {
        "tiers": [
            {"name": "static-analysis", "enabled": True},
        ]
    }
    result = _deep_merge(base, override)
    assert len(result["tiers"]) == 2
    sa = next(t for t in result["tiers"] if t["name"] == "static-analysis")
    ai = next(t for t in result["tiers"] if t["name"] == "ai-review")
    assert sa["enabled"] is True
    assert sa["commands"] == ["semgrep ."]  # preserved from base
    assert ai["enabled"] is True  # untouched


def test_merge_named_lists_preserves_order():
    base = [{"name": "a", "v": 1}, {"name": "b", "v": 2}]
    override = [{"name": "c", "v": 3}, {"name": "a", "v": 10}]
    result = _merge_named_lists(base, override)
    assert [r["name"] for r in result] == ["a", "b", "c"]
    assert result[0]["v"] == 10  # overridden
    assert result[1]["v"] == 2  # kept
    assert result[2]["v"] == 3  # appended


def test_deep_merge_replaces_plain_lists():
    """Non-named lists should still be replaced entirely."""
    base = {"tags": ["a", "b"]}
    override = {"tags": ["c"]}
    result = _deep_merge(base, override)
    assert result["tags"] == ["c"]
