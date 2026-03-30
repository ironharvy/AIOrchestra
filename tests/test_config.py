"""Tests for config loading."""

from aiorchestra.config import load_config, _deep_merge


def test_defaults_returned_when_no_file():
    config = load_config("/nonexistent/path.yaml")
    assert config["label"] == "claude"
    assert config["ai"]["max_retries"] == 3


def test_deep_merge():
    base = {"a": 1, "nested": {"x": 10, "y": 20}}
    override = {"a": 2, "nested": {"y": 99}}
    result = _deep_merge(base, override)
    assert result == {"a": 2, "nested": {"x": 10, "y": 99}}
