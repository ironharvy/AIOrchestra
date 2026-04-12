"""Review stage — multi-tier AI code review.

Tiers execute in order and short-circuit on failure:

  T3  ai-review          — primary AI reviews the diff (default: claude-code)
  T4  cross-model-review — second AI cross-checks (any provider: codex, claude-code, ollama, …)
  T5  human-required     — gate on human approval (label-gated)

T0 (lint/tests) and T1 (static analysis) run earlier in the validate stage.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aiorchestra.ai import create_provider, normalize_agent_family
from aiorchestra.stages._shell import run_command
from aiorchestra.stages.types import FeedbackResult, IssueData, PipelineConfig
from aiorchestra.templates import render_template

log = logging.getLogger(__name__)


def _get_diff(repo_root: str | None) -> str:
    result = run_command(["git", "diff", "origin/main...HEAD"], cwd=repo_root, logger=log)
    return result.stdout


def _get_tier(tiers: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((t for t in tiers if t.get("name") == name), None)


# -- T3: AI review (primary) ------------------------------------------------


def _run_ai_review(
    diff: str,
    config: PipelineConfig,
    tier_cfg: dict[str, Any],
    issue: IssueData | None,
    repo_root: str | None,
) -> FeedbackResult:
    """Run primary AI code review via the configured provider."""
    number = issue["number"] if issue else 0
    title = issue["title"] if issue else "unknown"

    prompt = render_template(
        "review",
        repo_root=repo_root,
        number=number,
        title=title,
        diff=diff,
    )

    ai_config = {**config.get("ai", {}), **tier_cfg}
    provider = create_provider(ai_config)
    result = provider.run(prompt, cwd=repo_root)

    if not result.success:
        return False, "AI review invocation failed."

    if "LGTM" in result.output:
        log.info("AI review (T3) passed.")
        return True, None

    log.info("AI review (T3) flagged issues: %.500s", result.output)
    log.debug("AI review (T3) full feedback: %s", result.output)
    return False, result.output


# -- T4: Cross-model / cross-agent review -----------------------------------

# When auto-selecting a cross-review agent, pick a *different* agent family
# from the one that wrote the code.  Order matters: first match wins.
_CROSS_AGENT_PREFERENCES: dict[str, list[str]] = {
    "claude": ["codex", "gemini", "jules", "ollama"],
    "codex": ["claude-code", "gemini", "jules", "ollama"],
    "gemini": ["claude-code", "codex", "jules", "ollama"],
    "jules": ["claude-code", "codex", "gemini", "ollama"],
}


def pick_cross_agent(implementation_provider: str) -> str:
    """Return the preferred cross-review provider for *implementation_provider*.

    If the implementing agent is ``claude-code``, the first choice for review
    is ``codex`` (and vice versa).  Falls back to ``ollama`` when no
    dedicated agent is available.
    """
    family = normalize_agent_family(implementation_provider)
    candidates = _CROSS_AGENT_PREFERENCES.get(family, ["ollama"])
    return candidates[0]


def _build_cross_review_provider_cfg(tier_cfg: dict[str, Any]) -> dict:
    """Build a flat provider config dict from a cross-model tier config.

    Supports both the legacy Ollama-nested format::

        {"provider": "ollama", "ollama": {"endpoint": "...", "model": "..."}}

    and a flat format for any provider::

        {"provider": "codex", "model": "o4-mini", "approval_mode": "suggest"}
    """
    provider_name = tier_cfg.get("provider", "ollama")
    if provider_name == "ollama" and "ollama" in tier_cfg:
        return {**tier_cfg["ollama"], "provider": "ollama"}
    return {**tier_cfg, "provider": provider_name}


def _run_cross_model_review(
    diff: str,
    tier_cfg: dict[str, Any],
    issue: IssueData | None,
    repo_root: str | None,
) -> FeedbackResult:
    """Run cross-model review via a different provider.

    Supports any registered provider (codex, claude-code, jules, ollama, …).
    When ``strict`` is true in the tier config, unavailability or invocation
    failure is a hard error instead of a graceful skip.
    """
    number = issue["number"] if issue else 0
    title = issue["title"] if issue else "unknown"
    strict = tier_cfg.get("strict", False)

    prompt = render_template(
        "review_cross_model",
        repo_root=repo_root,
        number=number,
        title=title,
        diff=diff,
    )

    provider_cfg = _build_cross_review_provider_cfg(tier_cfg)
    provider_name = provider_cfg.get("provider", "ollama")
    model = provider_cfg.get("model", "default")
    log.info("Cross-model review (T4) using provider=%s model=%s", provider_name, model)
    provider = create_provider(provider_cfg)

    if not provider.available():
        if strict:
            msg = f"Cross-review provider {provider_name!r} is not available"
            log.error("%s — failing (strict mode)", msg)
            return False, msg
        log.warning("Provider %s not available — skipping cross-model review (T4)", provider_name)
        return True, None

    system_prompt = (
        "You are a code reviewer. Review the diff for bugs, security issues, and "
        "logic errors. If the code looks good, respond with exactly: LGTM. "
        "If there are issues, describe them clearly with severity levels."
    )

    result = provider.run(prompt, system=system_prompt, cwd=repo_root)

    if not result.success:
        if strict:
            msg = f"Cross-review provider {provider_name!r} invocation failed"
            log.error("%s — failing (strict mode)", msg)
            return False, result.output or msg
        log.warning("Cross-model review returned no response — skipping (T4)")
        return True, None

    if "LGTM" in result.output:
        log.info("Cross-model review (T4) passed.")
        return True, None

    log.info("Cross-model review (T4) flagged issues: %.500s", result.output)
    log.debug("Cross-model review (T4) full feedback: %s", result.output)
    return False, result.output


# -- T5: Human-required gate -------------------------------------------------


def _check_human_required(
    tier_cfg: dict[str, Any],
    issue: IssueData | None,
) -> FeedbackResult:
    """Check if human review is required based on issue labels."""
    if not issue:
        return True, None

    gated_labels = set(tier_cfg.get("labels", []))
    issue_labels = {
        lbl if isinstance(lbl, str) else lbl.get("name", "") for lbl in issue.get("labels", [])
    }

    matching = gated_labels & issue_labels
    if matching:
        log.info(
            "Human review required — issue has gated labels: %s",
            ", ".join(sorted(matching)),
        )
        return False, (
            f"HUMAN_REVIEW_REQUIRED: This change touches labels [{', '.join(sorted(matching))}] "
            f"that require human approval before merge."
        )

    log.info("Human review gate (T5) — no gated labels, passing.")
    return True, None


# -- Public entry point ------------------------------------------------------


def review(
    repo: str,
    branch: str,
    config: PipelineConfig,
    issue: IssueData | None = None,
    repo_root: str | None = None,
) -> FeedbackResult:
    """Run tiered code review. Returns (passed, feedback).

    Tiers execute in order; each must pass before the next runs.
    Disabled tiers are skipped. If no tiers are enabled, defaults to
    the legacy single-AI-review behaviour.
    """
    review_cfg = config.get("review", {})
    tiers = review_cfg.get("tiers", [])

    diff = _get_diff(repo_root)
    if not diff.strip():
        log.warning("No diff to review.")
        return True, None

    review_start = time.monotonic()
    tier_durations: dict[str, float] = {}

    # If no tiers configured, fall back to legacy behaviour (single AI review)
    if not tiers:
        t0 = time.monotonic()
        result = _run_ai_review(diff, config, review_cfg, issue, repo_root)
        tier_durations["ai-review"] = time.monotonic() - t0
        elapsed = time.monotonic() - review_start
        log.info(
            "[review] completed in %.1fs (ai-review: %.1fs)",
            elapsed,
            tier_durations["ai-review"],
        )
        return result

    impl_provider = config.get("ai", {}).get("provider", "claude-code")

    for tier_cfg in tiers:
        name = tier_cfg.get("name", "unknown")
        if not tier_cfg.get("enabled", False):
            log.debug("Tier '%s' disabled, skipping.", name)
            continue

        log.info("Running review tier: %s", name)
        t0 = time.monotonic()

        if name == "ai-review":
            ok, feedback = _run_ai_review(diff, config, tier_cfg, issue, repo_root)
        elif name in ("cross-model-review", "cross-agent-review"):
            resolved_cfg = _resolve_cross_review_tier(tier_cfg, impl_provider, repo)
            ok, feedback = _run_cross_model_review(diff, resolved_cfg, issue, repo_root)
        elif name == "human-required":
            ok, feedback = _check_human_required(tier_cfg, issue)
        elif name == "static-analysis":
            log.debug("Tier '%s' handled by validate stage, skipping.", name)
            continue
        else:
            log.warning("Unknown review tier '%s', skipping.", name)
            continue

        tier_durations[name] = time.monotonic() - t0

        if not ok:
            log.info("Review tier '%s' failed — stopping.", name)
            elapsed = time.monotonic() - review_start
            tier_summary = ", ".join(f"{k}: {v:.1f}s" for k, v in tier_durations.items())
            log.info("[review] completed in %.1fs (%s)", elapsed, tier_summary)
            return False, feedback

    elapsed = time.monotonic() - review_start
    tier_summary = ", ".join(f"{k}: {v:.1f}s" for k, v in tier_durations.items())
    log.info("[review] completed in %.1fs (%s)", elapsed, tier_summary)
    log.info("All review tiers passed.")
    return True, None


def _resolve_cross_review_tier(
    tier_cfg: dict[str, Any],
    impl_provider: str,
    repo: str,
) -> dict[str, Any]:
    """Resolve ``"auto"`` provider to a concrete cross-review agent.

    When the tier's ``provider`` is ``"auto"``, :func:`pick_cross_agent`
    selects a different agent family from the one that implemented the code.
    The ``repo`` is injected for providers like Jules that need it.
    """
    provider = tier_cfg.get("provider", "ollama")
    if provider == "auto":
        provider = pick_cross_agent(impl_provider)
        log.info(
            "Auto-selected cross-review provider: %s (implementation: %s)",
            provider,
            impl_provider,
        )
    resolved = {**tier_cfg, "provider": provider}
    # Jules needs the repo for remote sessions.
    if normalize_agent_family(provider) == "jules" and "repo" not in resolved:
        resolved["repo"] = repo
    return resolved
