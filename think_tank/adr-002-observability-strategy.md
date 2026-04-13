# ADR-002: Observability Strategy — Sentry + Langfuse

**Status:** Accepted
**Date:** 2026-04-13
**Author:** AI evaluation

## Context

AIOrchestra orchestrates multi-step AI pipelines (discover → implement →
validate → review → publish) across several agent providers (Claude, Codex,
Gemini, Ollama). Today there is:

- No structured error reporting beyond Python logs
- No visibility into AI provider calls — token usage, cost, latency, prompt
  quality are all opaque
- No way to correlate a production failure with the pipeline stages that led
  up to it

Two tools have been proposed to address these gaps:

- **Sentry** (PR #47) — error tracking, breadcrumbs, exception capture
- **Langfuse** (issue #34) — LLM-specific tracing: prompts, completions,
  tokens, cost, per-generation latency

The two were initially seen as competing. They are not. They address
**different, non-overlapping** observability layers.

## Decision

Adopt **both**, with clear non-overlapping roles:

| Layer | Tool | What it captures |
|---|---|---|
| Runtime errors | **Sentry** | Unhandled exceptions, stack traces, breadcrumbs for the stage sequence, issue/repo tags |
| LLM tracing | **Langfuse** | Per-call prompt, completion, model, token counts, cost, latency; per-issue trace aggregating all AI calls |

Both are **optional** (off by default) and gated on environment variables /
config. Neither introduces a hard runtime dependency.

## Rationale

### Why Sentry

- Pipeline runs in forked child processes (`_child_main` uses `os._exit`).
  Plain logs are lost when the child dies; Sentry captures the stack trace
  before exit.
- Breadcrumbs give a lightweight audit trail of which stages completed before
  an error, without paying the cost of full tracing.
- Cheap free tier covers realistic volumes for this project.

### Why Langfuse

- AIOrchestra's product *is* AI calls. Cost-per-issue, token-per-stage, and
  prompt-quality signals are the most actionable data we can collect.
- Provider comparison (Claude vs Codex vs Gemini) needs apples-to-apples
  metrics — Langfuse aggregates by model/provider natively.
- Free tier (self-host or cloud) covers development and small teams.

### Why both — and not one or the other

- Sentry is not a tracing tool — its "performance" product exists but is not
  optimized for LLM workflows and costs more.
- Langfuse is not an error-tracking tool — it captures generation errors but
  not unhandled Python exceptions outside LLM calls (shell commands, git
  operations, disk-space checks, etc.).
- A failure during `publish` or `prepare` never touches an LLM; Langfuse
  wouldn't see it. Sentry would.
- A prompt-quality regression (reviews silently getting worse) never raises an
  exception; Sentry wouldn't see it. Langfuse would.

## Implementation Principles

Both integrations MUST follow these rules:

1. **Optional dependency.** Install via extras (`pip install
   aiorchestra[sentry]`, `aiorchestra[observability]` for Langfuse).
2. **Graceful degradation.** All public functions are safe to call without the
   SDK installed — no imports fail, no exceptions raised.
3. **Off by default.** Enable via env var (`SENTRY_DSN`, `LANGFUSE_PUBLIC_KEY`)
   or explicit config. No telemetry leaves the machine without opt-in.
4. **No PII by default.** `send_default_pii=False` for Sentry; no user tokens
   or GitHub credentials in traces.
5. **Idempotent init.** Both `init()` functions must be safe to call multiple
   times (CLI may invoke from different subcommands).
6. **Flush before exit.** Forked children (`_child_main`) must call
   `flush(timeout=2)` before `os._exit` so async-queued events are sent.
7. **Consistent context.** Both systems tag/annotate with `repo`, `issue_number`,
   and `provider` so events can be correlated across tools.

## Data Classification

What each tool sees:

| Data | Sentry | Langfuse | Notes |
|---|---|---|---|
| Repo full_name | ✓ | ✓ | Public info for open-source repos; still contextual PII for private |
| Issue title | ✓ (context) | ✓ (input) | Same concern |
| Issue body | — | ✓ (input) | Langfuse stores the full prompt |
| AI completions | — | ✓ (output) | Langfuse stores model responses |
| Stack traces | ✓ | — | Python exceptions only |
| Tokens / cost | — | ✓ | Langfuse native |
| GitHub token | — | — | Must never be sent; tests should assert this |

**Privacy guard:** add a test that asserts `GH_TOKEN`/`GITHUB_TOKEN` env vars
never appear in the payloads of either integration.

## Alternatives Considered

- **OpenTelemetry + self-hosted backend (Grafana Tempo, Honeycomb)** —
  Richer, but significant operational overhead. Revisit if project grows
  beyond single-operator use.
- **Structured logging only (no external service)** — Zero cost, but no
  aggregation, no cost tracking, no comparison across runs. Rejected: the
  project's value hinges on AI calls; flying blind is a bigger risk than one
  optional dep.
- **Langfuse only** — Covers the LLM layer but misses non-LLM exceptions,
  which empirically are a significant share of failures (git, disk, CLI
  auth).
- **Sentry only** — Covers errors but misses the actionable AI signal.

## Consequences

**Positive:**
- Cost-per-issue becomes measurable; provider comparison becomes empirical.
- Production failures get stack traces instead of lost child-process logs.
- Both tools are free-tier friendly; operational cost is near zero for small
  teams.

**Negative:**
- Two systems to configure, not one. Mitigated by shared context conventions
  (same tags in both).
- Two optional deps to keep compatible in CI test matrix.
- Users wanting full observability must sign up for two services. Mitigated by
  both being fully optional.

## Rollout

1. Land this ADR (no code change).
2. Rebase PR #47 on current `main`, address the 5 blocking items from the
   self-review, implement the `flush()` wrapper, link this ADR.
3. Implement issue #34 on a new branch following the same principles. Share
   per-issue `trace_id` with Sentry tags so events can be cross-referenced.
4. Add privacy test per the Data Classification section.
