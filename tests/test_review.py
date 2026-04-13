"""Tests for the multi-tier review stage."""

import types

from aiorchestra.ai import InvokeResult
from aiorchestra.stages import review as rev_mod
from aiorchestra.stages.review import (
    _build_cross_review_provider_cfg,
    _check_human_required,
    _resolve_cross_review_tier,
    _run_ai_review,
    _run_cross_model_review,
    pick_cross_agent,
    review,
)

ISSUE = {"number": 42, "title": "Add feature X"}
DIFF = "+def foo():\n+    return 42\n"


class FakeProvider:
    """Configurable fake provider for testing."""

    def __init__(self, output="LGTM", success=True, is_available=True):
        self._output = output
        self._success = success
        self._is_available = is_available
        self.called = False
        self.last_prompt = None

    def run(self, prompt, *, system=None, capture_output=False, cwd=None):
        self.called = True
        self.last_prompt = prompt
        return InvokeResult(success=self._success, output=self._output)

    def available(self):
        return self._is_available


def _patch_provider(monkeypatch, output="LGTM", success=True, is_available=True):
    """Patch create_provider on the review module to return a FakeProvider."""
    provider = FakeProvider(output=output, success=success, is_available=is_available)
    monkeypatch.setattr(
        rev_mod,
        "create_provider",
        lambda cfg: provider,
    )
    return provider


# ---------------------------------------------------------------------------
# T3: AI review
# ---------------------------------------------------------------------------


def test_ai_review_passes_on_lgtm(monkeypatch):
    _patch_provider(monkeypatch, output="LGTM")
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: f"review {kw['number']}",
    )

    ok, feedback = _run_ai_review(DIFF, {}, {}, ISSUE, None)
    assert ok
    assert feedback is None


def test_ai_review_fails_on_issues(monkeypatch):
    _patch_provider(monkeypatch, output="Bug: off-by-one in loop")
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "review prompt",
    )

    ok, feedback = _run_ai_review(DIFF, {}, {}, ISSUE, None)
    assert not ok
    assert "off-by-one" in feedback


def test_ai_review_fails_on_invocation_error(monkeypatch):
    _patch_provider(monkeypatch, success=False)
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
    _patch_provider(monkeypatch, output="LGTM")
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
    _patch_provider(monkeypatch, output="critical: SQL injection in query builder")
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
    _patch_provider(monkeypatch, is_available=False)
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "cross model prompt",
    )

    tier_cfg = {"provider": "ollama", "ollama": {}}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert ok  # gracefully passes when unavailable


def test_cross_model_skipped_on_failed_response(monkeypatch):
    _patch_provider(monkeypatch, success=False)
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "cross model prompt",
    )

    tier_cfg = {"provider": "ollama", "ollama": {}}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert ok  # gracefully passes when response fails


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
    _patch_provider(monkeypatch, output="LGTM")
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

    # AI review will flag issues (T3 fails), cross-model (T4) should never run.
    call_log = []

    def fake_create_provider(cfg):
        provider_name = cfg.get("provider", "claude-code")
        if provider_name in ("claude-code",):
            # T3 ai-review returns failure
            p = FakeProvider(output="Bug: memory leak")
            return p
        # T4 cross-model
        p = FakeProvider(output="LGTM")
        call_log.append("t4-created")
        return p

    monkeypatch.setattr(rev_mod, "create_provider", fake_create_provider)
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "template",
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
    assert not ok
    assert "memory leak" in feedback
    assert "t4-created" not in call_log  # T4 never executed because T3 failed


def test_review_skips_disabled_tiers(monkeypatch):
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )

    provider = _patch_provider(monkeypatch, output="LGTM")
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
    assert not provider.called


def test_review_skips_static_analysis_without_warning(monkeypatch, caplog):
    """static-analysis is handled by validate, so review should skip it silently."""
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )

    provider = _patch_provider(monkeypatch, output="LGTM")
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "template",
    )

    config = {
        "review": {
            "tiers": [
                {"name": "static-analysis", "enabled": True, "commands": ["semgrep"]},
                {"name": "ai-review", "enabled": True, "provider": "claude-code"},
            ]
        }
    }

    import logging

    with caplog.at_level(logging.DEBUG, logger="aiorchestra.stages.review"):
        ok, feedback = review("owner/repo", "branch", config, issue=ISSUE)

    assert ok
    assert feedback is None
    assert provider.called
    assert "Unknown review tier" not in caplog.text
    assert "handled by validate stage" in caplog.text


def test_review_falls_back_to_legacy_when_no_tiers(monkeypatch):
    """When no tiers are configured, falls back to single AI review."""
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )
    _patch_provider(monkeypatch, output="LGTM")
    monkeypatch.setattr(
        rev_mod,
        "render_template",
        lambda name, **kw: "template",
    )

    # Config with review enabled but no tiers key
    config = {"review": {"enabled": True, "provider": "claude-code"}}

    ok, feedback = review("owner/repo", "branch", config, issue=ISSUE)
    assert ok


# ---------------------------------------------------------------------------
# pick_cross_agent
# ---------------------------------------------------------------------------


def test_pick_cross_agent_claude_prefers_codex():
    assert pick_cross_agent("claude-code") == "codex"


def test_pick_cross_agent_codex_prefers_claude():
    assert pick_cross_agent("codex") == "claude-code"


def test_pick_cross_agent_jules_prefers_claude():
    assert pick_cross_agent("jules") == "claude-code"


def test_pick_cross_agent_gemini_prefers_claude():
    assert pick_cross_agent("gemini") == "claude-code"


def test_pick_cross_agent_claude_has_gemini_in_fallback():
    """Gemini is in the preference list for claude (after codex)."""
    from aiorchestra.stages.review import _CROSS_AGENT_PREFERENCES

    assert "gemini" in _CROSS_AGENT_PREFERENCES["claude"]


def test_pick_cross_agent_unknown_falls_back_to_ollama():
    assert pick_cross_agent("some-custom-thing") == "ollama"


# ---------------------------------------------------------------------------
# _build_cross_review_provider_cfg
# ---------------------------------------------------------------------------


def test_build_cfg_ollama_nested():
    tier = {"provider": "ollama", "ollama": {"model": "phi3", "endpoint": "http://h:1234"}}
    cfg = _build_cross_review_provider_cfg(tier)
    assert cfg["provider"] == "ollama"
    assert cfg["model"] == "phi3"
    assert cfg["endpoint"] == "http://h:1234"


def test_build_cfg_flat_codex():
    tier = {"provider": "codex", "model": "o4-mini", "approval_mode": "suggest"}
    cfg = _build_cross_review_provider_cfg(tier)
    assert cfg["provider"] == "codex"
    assert cfg["model"] == "o4-mini"


# ---------------------------------------------------------------------------
# _resolve_cross_review_tier
# ---------------------------------------------------------------------------


def test_resolve_auto_picks_cross_agent():
    tier = {"provider": "auto", "strict": True}
    resolved = _resolve_cross_review_tier(tier, "claude-code", "owner/repo")
    assert resolved["provider"] == "codex"
    assert resolved["strict"] is True


def test_resolve_auto_for_codex_picks_claude():
    tier = {"provider": "auto"}
    resolved = _resolve_cross_review_tier(tier, "codex", "owner/repo")
    assert resolved["provider"] == "claude-code"


def test_resolve_auto_for_jules_injects_repo():
    tier = {"provider": "auto"}
    resolved = _resolve_cross_review_tier(tier, "codex", "owner/repo")
    # codex -> claude-code, no repo needed
    assert "repo" not in resolved

    tier2 = {"provider": "jules"}
    resolved2 = _resolve_cross_review_tier(tier2, "claude-code", "owner/repo")
    assert resolved2["repo"] == "owner/repo"


def test_resolve_explicit_provider_unchanged():
    tier = {"provider": "codex", "model": "o4-mini"}
    resolved = _resolve_cross_review_tier(tier, "claude-code", "owner/repo")
    assert resolved["provider"] == "codex"
    assert resolved["model"] == "o4-mini"


# ---------------------------------------------------------------------------
# Strict mode (cross-model review)
# ---------------------------------------------------------------------------


def test_cross_model_strict_fails_when_unavailable(monkeypatch):
    _patch_provider(monkeypatch, is_available=False)
    monkeypatch.setattr(rev_mod, "render_template", lambda name, **kw: "prompt")

    tier_cfg = {"provider": "codex", "strict": True}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert not ok
    assert "not available" in feedback


def test_cross_model_strict_fails_on_invocation_error(monkeypatch):
    _patch_provider(monkeypatch, success=False)
    monkeypatch.setattr(rev_mod, "render_template", lambda name, **kw: "prompt")

    tier_cfg = {"provider": "codex", "strict": True}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert not ok


def test_cross_model_non_strict_skips_when_unavailable(monkeypatch):
    """Non-strict mode (default) gracefully skips unavailable providers."""
    _patch_provider(monkeypatch, is_available=False)
    monkeypatch.setattr(rev_mod, "render_template", lambda name, **kw: "prompt")

    tier_cfg = {"provider": "codex", "strict": False}
    ok, feedback = _run_cross_model_review(DIFF, tier_cfg, ISSUE, None)
    assert ok


# ---------------------------------------------------------------------------
# Full tiered review with cross-agent tier
# ---------------------------------------------------------------------------


def test_review_cross_agent_tier_auto_selects_reviewer(monkeypatch):
    """cross-agent-review tier with provider=auto picks a different agent."""
    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )
    _patch_provider(monkeypatch, output="LGTM")
    monkeypatch.setattr(rev_mod, "render_template", lambda name, **kw: "prompt")

    config = {
        "ai": {"provider": "claude-code"},
        "review": {
            "tiers": [
                {
                    "name": "cross-agent-review",
                    "enabled": True,
                    "provider": "auto",
                    "strict": False,
                },
            ]
        },
    }

    ok, feedback = review("owner/repo", "branch", config, issue=ISSUE)
    assert ok


def test_review_cross_agent_codex_reviews_claude(monkeypatch):
    """When claude-code implements, codex should be selected for cross-review."""
    created_providers = []

    monkeypatch.setattr(
        rev_mod,
        "run_command",
        lambda cmd, cwd=None, logger=None: types.SimpleNamespace(
            returncode=0, stdout=DIFF, stderr=""
        ),
    )
    monkeypatch.setattr(rev_mod, "render_template", lambda name, **kw: "prompt")

    def tracking_create_provider(cfg):
        created_providers.append(cfg.get("provider"))
        return FakeProvider(output="LGTM")

    monkeypatch.setattr(rev_mod, "create_provider", tracking_create_provider)

    config = {
        "ai": {"provider": "claude-code"},
        "review": {
            "tiers": [
                {"name": "cross-agent-review", "enabled": True, "provider": "auto"},
            ]
        },
    }

    ok, feedback = review("owner/repo", "branch", config, issue=ISSUE)
    assert ok
    assert "codex" in created_providers
