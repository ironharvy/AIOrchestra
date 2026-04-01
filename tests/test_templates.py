"""Tests for template loading and resolution."""

import tempfile
from pathlib import Path

from aiorchestra.templates import load_template, render_template


def test_builtin_templates_exist():
    for name in ["implement", "fix_validation", "fix_ci", "review", "fix_review"]:
        template = load_template(name)
        assert "{number}" in template


def test_render_template():
    result = render_template(
        "implement", number=42, title="Add feature", body="Details here",
        osint_context="",
    )
    assert "42" in result
    assert "Add feature" in result
    assert "Details here" in result


def test_repo_override():
    with tempfile.TemporaryDirectory() as tmpdir:
        override_dir = Path(tmpdir) / ".aiorchestra" / "templates"
        override_dir.mkdir(parents=True)
        (override_dir / "implement.md").write_text("Custom: {number}")

        result = render_template("implement", repo_root=tmpdir, number=99)
        assert result == "Custom: 99"


def test_repo_override_falls_back():
    with tempfile.TemporaryDirectory() as tmpdir:
        # No .aiorchestra/templates/ dir — should fall back to built-in
        result = load_template("implement", repo_root=tmpdir)
        assert "{number}" in result
