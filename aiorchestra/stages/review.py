"""Review stage — multi-tier AI code review.

Tiers execute in order and short-circuit on failure:

  T3  ai-review          — primary AI reviews the diff (default: claude-code)
  T4  cross-model-review — second AI cross-checks (default: ollama/local)
  T5  human-required     — gate on human approval (label-gated)

T0 (lint/tests) and T1 (static analysis) run earlier in the validate stage.
"""

from __future__ import annotations

import logging
from typing import Any

from aiorchestra.ai.provider import create_provider
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
    result = provider.run(prompt, capture_output=True, cwd=repo_root)

    if not result.success:
        return False, "AI review invocation failed."

    if "LGTM" in result.output:
        log.info("AI review (T3) passed.")
        return True, None

    log.info("AI review (T3) flagged issues.")
    return False, result.output


# -- T4: Cross-model review -------------------------------------------------


def _run_cross_model_review(
    diff: str,
    tier_cfg: dict[str, Any],
    issue: IssueData | None,
    repo_root: str | None,
) -> FeedbackResult:
    """Run cross-model review via a different provider (default: Ollama)."""
    number = issue["number"] if issue else 0
    title = issue["title"] if issue else "unknown"

    prompt = render_template(
        "review_cross_model",
        repo_root=repo_root,
        number=number,
        title=title,
        diff=diff,
    )

    # Build provider config — for Ollama tiers the endpoint/model/timeout
    # live under a nested "ollama" key in the config.
    provider_name = tier_cfg.get("provider", "ollama")
    if provider_name == "ollama":
        provider_cfg = {**tier_cfg.get("ollama", {}), "provider": "ollama"}
    else:
        provider_cfg = {**tier_cfg, "provider": provider_name}

    provider = create_provider(provider_cfg)

    if not provider.available():
        log.warning("Provider %s not available — skipping cross-model review (T4)", provider_name)
        return True, None

    system_prompt = (
        "You are a code reviewer. Review the diff for bugs, security issues, and "
        "logic errors. If the code looks good, respond with exactly: LGTM. "
        "If there are issues, describe them clearly with severity levels."
    )

    result = provider.run(prompt, system=system_prompt)

    if not result.success:
        log.warning("Cross-model review returned no response — skipping (T4)")
        return True, None

    if "LGTM" in result.output:
        log.info("Cross-model review (T4) passed.")
        return True, None

    log.info("Cross-model review (T4) flagged issues.")
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

    # If no tiers configured, fall back to legacy behaviour (single AI review)
    if not tiers:
        return _run_ai_review(diff, config, review_cfg, issue, repo_root)

    for tier_cfg in tiers:
        name = tier_cfg.get("name", "unknown")
        if not tier_cfg.get("enabled", False):
            log.debug("Tier '%s' disabled, skipping.", name)
            continue

        log.info("Running review tier: %s", name)

        if name == "ai-review":
            ok, feedback = _run_ai_review(diff, config, tier_cfg, issue, repo_root)
        elif name == "cross-model-review":
            ok, feedback = _run_cross_model_review(diff, tier_cfg, issue, repo_root)
        elif name == "human-required":
            ok, feedback = _check_human_required(tier_cfg, issue)
        else:
            log.warning("Unknown review tier '%s', skipping.", name)
            continue

        if not ok:
            log.info("Review tier '%s' failed — stopping.", name)
            return False, feedback

    log.info("All review tiers passed.")
    return True, None
