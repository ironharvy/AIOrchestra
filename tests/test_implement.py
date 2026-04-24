"""Tests for the implement stage (prompt assembly, feedback truncation)."""

from aiorchestra.stages import implement as impl_mod
from aiorchestra.stages.implement import _MAX_ERROR_TEXT_BYTES, _truncate_error_text


def test_truncate_short_error_text_unchanged():
    text = "only a few bytes of feedback"
    assert _truncate_error_text(text) == text


def test_truncate_long_error_text_keeps_head_and_tail():
    body = "A" * (_MAX_ERROR_TEXT_BYTES * 3)
    prefix = "START-MARKER:"
    suffix = ":END-MARKER"
    oversized = prefix + body + suffix

    result = _truncate_error_text(oversized)

    assert len(result.encode("utf-8")) < len(oversized.encode("utf-8"))
    # Both ends survive so the AI still sees real context on either side.
    assert result.startswith(prefix)
    assert result.endswith(suffix)
    # And the middle is replaced with a human-readable truncation marker.
    assert "truncated" in result


def test_build_prompt_truncates_error_text(monkeypatch):
    captured = {}

    def fake_render(name, **kwargs):
        captured["kwargs"] = kwargs
        return "rendered"

    monkeypatch.setattr(impl_mod, "render_template", fake_render)

    huge = "X" * (_MAX_ERROR_TEXT_BYTES * 2)
    impl_mod._build_prompt(
        {"number": 1, "title": "t", "body": ""},
        prompt_name="fix_validation",
        error_text=huge,
    )

    assert "errors" in captured["kwargs"]
    assert len(captured["kwargs"]["errors"].encode("utf-8")) <= _MAX_ERROR_TEXT_BYTES + 512
    assert "truncated" in captured["kwargs"]["errors"]
