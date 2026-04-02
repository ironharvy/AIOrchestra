"""Tests for the multi-tier review stage."""

import types

from aiorchestra.ai.claude import InvokeResult
from aiorchestra.stages import review as rev_mod
from aiorchestra.stages.review import (
    _check_human_required,
    _run_ai_review,
    _run_cross_model_review,
    review,
)

ISSUE = {"number": 42, "title": "Add feature X"}
DIFF = "+def foo():\n+    return 42\n"


# ---------------------------------------------------------------------------
# T3: AI review
# ---------------------------------------------------------------------------


def test_ai_review_passes_on_lgtm(monkeypatch):
    monkeypatch.setattr(
        rev_mod,
        "invoke_claude",
        lambda prompt, cfg, capture_output=False, cwd=None: InvokeResult(
            success=True, output="LGTM"
        ),
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: f"review {kw['number']}",
    )

    ok, feedback = _run_ai_review(DIFF, {}, {}, ISSUE, None)
    assert ok
    assert feedback is None


def test_ai_review_fails_on_issues(monkeypatch):
    monkeypatch.setattr(
        rev_mod,
        "invoke_claude",
        lambda prompt, cfg, capture_output=False, cwd=None: InvokeResult(
            success=True, output="Bug: off-by-one in loop"
        ),
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "review prompt",
    )

    ok, feedback = _run_ai_review(DIFF, {}, {}, ISSUE, None)
    assert not ok
    assert "off-by-one" in feedback


def test_ai_review_fails_on_invocation_error(monkeypatch):
    monkeypatch.setattr(
        rev_mod,
        "invoke_claude",
        lambda prompt, cfg, capture_output=False, cwd=None: InvokeResult(success=False),
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "review prompt",
    )

    ok, feedback = _run_ai_review(DIFF, {}, {}, ISSUE, None)
    assert not ok
    assert "failed" in feedback


# ---------------------------------------------------------------------------
# T4: Cross-model review (Ollama)
# ---------------------------------------------------------------------------


def test_cross_model_ollama_passes_on_lgtm(monkeypatch):
    monkeypatch.setattr(rev_mod, "ollama_available", lambda cfg: True)
    monkeypatch.setattr(
        rev_mod,
        "invoke_ollama",
        lambda prompt, cfg, system=None: "LGTM",
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "cross model prompt",
    )

    tier_cfg = {"provider": "ollama", "ollama": {"endpoint": "http://localhost:11434"}}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert ok
    assert feedback is None


def test_cross_model_ollama_flags_issues(monkeypatch):
    monkeypatch.setattr(rev_mod, "ollama_available", lambda cfg: True)
    monkeypatch.setattr(
        rev_mod,
        "invoke_ollama",
        lambda prompt, cfg, system=None: "critical: SQL injection in query builder",
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "cross model prompt",
    )

    tier_cfg = {"provider": "ollama", "ollama": {}}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert not ok
    assert "SQL injection" in feedback


def test_cross_model_skipped_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(rev_mod, "ollama_available", lambda cfg: False)
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "cross model prompt",
    )

    tier_cfg = {"provider": "ollama", "ollama": {}}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert ok  # gracefully passes when unavailable


def test_cross_model_skipped_on_none_response(monkeypatch):
    monkeypatch.setattr(rev_mod, "ollama_available", lambda cfg: True)
    monkeypatch.setattr(
        rev_mod,
        "invoke_ollama",
        lambda prompt, cfg, system=None: None,
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "cross model prompt",
    )

    tier_cfg = {"provider": "ollama", "ollama": {}}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert ok  # gracefully passes when response is None


# ---------------------------------------------------------------------------
# T5: Human-required gate
# ---------------------------------------------------------------------------


def test_human_required_blocks_on_matching_label():
    tier_cfg = {"labels": ["security", "breaking-change"]}
    issue = {"number": 1, "title": "Fix", "labels": ["security", "bug"]}

    ok, feedback = _check_human_required(tier_cfg, issue)
    assert not ok
    assert "HUMAN_REVIEW_REQUIRED" in feedback
    assert "security" in feedback


def test_human_required_passes_when_no_matching_labels():
    tier_cfg = {"labels": ["security", "breaking-change"]}
    issue = {"number": 1, "title": "Fix", "labels": ["bug", "enhancement"]}

    ok, feedback = _check_human_required(tier_cfg, issue)
    assert ok
    assert feedback is None


def test_human_required_passes_with_no_issue():
    tier_cfg = {"labels": ["security"]}
    ok, feedback = _check_human_required(tier_cfg, None)
    assert ok


def test_human_required_passes_with_no_labels_on_issue():
    tier_cfg = {"labels": ["security"]}
    issue = {"number": 1, "title": "Fix"}

    ok, feedback = _check_human_required(tier_cfg, issue)
    assert ok


# ---------------------------------------------------------------------------
# Full tiered review (integration)
# ---------------------------------------------------------------------------


def test_review_empty_diff_passes(monkeypatch):
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
    )

    ok, feedback = review("owner/repo", "main", {})
    assert ok
    assert feedback is None


def test_review_runs_tiers_in_order(monkeypatch):
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )
    monkeypatch.setattr(
        rev_mod,
        "invoke_claude",
        lambda prompt, cfg, capture_output=False, cwd=None: InvokeResult(
            success=True, output="LGTM"
        ),
    )
    monkeypatch.setattr(rev_mod, "ollama_available", lambda cfg: True)
    monkeypatch.setattr(
        rev_mod,
        "invoke_ollama",
        lambda prompt, cfg, system=None: "LGTM",
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: f"template:{name}",
    )

    config = {
        "review": {
            "tiers": [
                {"name": "ai-review", "enabled": True, "provider": "claude-code"},
                {"name": "cross-model-review", "enabled": True, "provider": "ollama", "ollama": {}},
            ]
        }
    }

    ok, feedback = review("owner/repo", "branch", config, issue=ISSUE)
    assert ok
    assert feedback is None


def test_review_short_circuits_on_tier_failure(monkeypatch):
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )
    monkeypatch.setattr(
        rev_mod,
        "invoke_claude",
        lambda prompt, cfg, capture_output=False, cwd=None: InvokeResult(
            success=True, output="Bug: memory leak"
        ),
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "template",
    )

    ollama_called = False

    def spy_ollama(prompt, cfg, system=None):
        nonlocal ollama_called
        ollama_called = True
        return "LGTM"

    monkeypatch.setattr(rev_mod, "invoke_ollama", spy_ollama)
    monkeypatch.setattr(rev_mod, "ollama_available", lambda cfg: True)

    config = {
        "review": {
            "tiers": [
                {"name": "ai-review", "enabled": True, "provider": "claude-code"},
                {"name": "cross-model-review", "enabled": True, "provider": "ollama", "ollama": {}},
            ]
        }
    }

    ok, feedback = review("owner/repo", "branch", config, issue=ISSUE)
    assert not ok
    assert "memory leak" in feedback
    assert not ollama_called  # T4 never executed because T3 failed


def test_review_skips_disabled_tiers(monkeypatch):
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )

    claude_called = False

    def spy_claude(prompt, cfg, capture_output=False, cwd=None):
        nonlocal claude_called
        claude_called = True
        return InvokeResult(success=True, output="LGTM")

    monkeypatch.setattr(rev_mod, "invoke_claude", spy_claude)
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "template",
    )

    config = {
        "review": {
            "tiers": [
                {"name": "ai-review", "enabled": False},
                {"name": "cross-model-review", "enabled": False},
            ]
        }
    }

    ok, feedback = review("owner/repo", "branch", config, issue=ISSUE)
    assert ok
    assert not claude_called


def test_review_falls_back_to_legacy_when_no_tiers(monkeypatch):
    """When no tiers are configured, falls back to single AI review."""
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )
    monkeypatch.setattr(
        rev_mod,
        "invoke_claude",
        lambda prompt, cfg, capture_output=False, cwd=None: InvokeResult(
            success=True, output="LGTM"
        ),
    )
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "template",
    )

    # Config with review enabled but no tiers key
    config = {"review": {"enabled": True, "provider": "claude-code"}}

    ok, feedback = review("owner/repo", "branch", config, issue=ISSUE)
    assert ok
