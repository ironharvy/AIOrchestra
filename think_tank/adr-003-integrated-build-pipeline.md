# ADR-003: The Assembly Line — Integrating Daedalus, soai, and AIOrchestra

**Status:** Proposed (vision capture — no code change)
**Date:** 2026-06-12
**Author:** AI design session
**Scope:** Program-level. Spans three repos (DaedalusDSPy, soai, AIOrchestra).
Pieces may later be split into per-repo ADRs; this is the integrating record.

> This ADR captures a design conversation in which three previously separate
> projects converged into one system. It is deliberately broad. Nothing here is
> built yet except the soai composition-references decision (soai PR #7); the
> rest is the agreed direction and the open questions, recorded so the
> convergence isn't lost.

## Context

Three projects were being built in parallel, each solving one piece of
"AI builds software" without an explicit contract between them:

- **DaedalusDSPy** — simulates a dev company: role-based employees (CEO, BA,
  Tech Lead, PM, Researcher, Developer, QA, DevOps) collaborating through an
  SDLC. Its real value turned out to be **task decomposition and workflow**,
  not the code generation itself.
- **soai** — a registry of verified, reusable functions ("solutions") keyed by
  a "problem" statement. Reuse over recompute. Currently Phase 1: MongoDB
  `problems` + `solutions`, text search, no execution/verification.
- **AIOrchestra** — a GitHub-driven pipeline (discover → implement → validate →
  review → publish) that turns an issue into a merged PR under CI gates. Its
  value is being a **deterministic enforcer**, not being clever.

The realization driving this ADR: these are not three products. They are three
stages of **one assembly line** for AI-built software.

## Decision

Treat the three systems as a single pipeline with a clear division of agency:

| System | Role in the line | One-word identity |
|---|---|---|
| **Daedalus** | Decompose a request into well-specified tasks; decide | **Brain** |
| **soai** | Store/retrieve verified, composable solutions per problem | **Memory** |
| **AIOrchestra** | Implement one specified task under deterministic gates | **Hands** |

Two cross-cutting invariants hold the line together:

1. **GitHub is the substrate.** No in-memory handoff between systems. Every
   handoff is a durable artifact — a soai problem/solution record, a GitHub
   issue, a PR. This is Daedalus's existing thesis, promoted to the whole line.
2. **Tooling over rules.** Every quality expectation is a deterministic gate
   (linter, type checker, test, semgrep rule), never a sentence in an agent
   prompt. A rule in a prompt is a suggestion; a rule in a gate is a fact. If a
   rule can't be made into a check, it is a *review* concern, not a rule.

## The flow

```
user request
   │
   ▼
┌─────────────────────────── DAEDALUS (brain) ───────────────────────────┐
│ Tech Lead decomposes into tasks. Per task, classify:                   │
│   • function-shaped (pure in→out, reusable)  → soai-eligible           │
│   • project-specific (wiring, UI, config)    → straight to repo issue  │
│ For each function-shaped task:                                         │
│   define CONTRACT (statement + signature)                              │
│   author TESTS (QA writes examples; MVP: Tech Lead does both)          │
└────────────────────────────────┬───────────────────────────────────────┘
                                  ▼
┌─────────────────────────── soai (memory) ──────────────────────────────┐
│ search for the problem. Outcomes:                                       │
│   • exact solution exists      → REUSE, no issue created (best case)    │
│   • partial / composable parts → proceed, carry candidate solution IDs  │
│   • missing well-defined parts → register them as new problems (recurse)│
│ register the problem (statement + tests). Parent waits for its parts.   │
└────────────────────────────────┬───────────────────────────────────────┘
                                  ▼
┌──────────────── COMPOSER (Daedalus Researcher/Tech Lead) ───────────────┐
│ Sits between problem-submission and implementation. Writes a GitHub     │
│ issue that EMBEDS: the contract, the immutable tests, and candidate     │
│ soai solution IDs (signatures + descriptions) to prefer composing.      │
│ The issue is the complete, self-contained handoff. (NOT AIOrchestra's   │
│ job to search soai — keep the enforcer dumb and reproducible.)          │
└────────────────────────────────┬───────────────────────────────────────┘
                                  ▼
┌─────────────────────── AIOrchestra (hands) ─────────────────────────────┐
│ implement the issue exactly. Tests are a READ-ONLY acceptance gate.     │
│ Run the gate set (below). LLM repair loop on failures, N times.         │
│   • green + reviewed → publish: POST solution back to soai, declaring   │
│     which solution IDs it actually composed (dependency edges).         │
│   • can't go green in budget → close as needs-decomposition; bounce     │
│     the task back to the Tech Lead. (A hint, not a verdict.)            │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key sub-decisions

### D1 — Test authorship is upstream of, and independent from, implementation

The test belongs to the **problem**, not the solution (soai's own contract:
"a problem statement plus input→output examples that double as the test suite").
The implementer (AIOrchestra) must never author the oracle it is graded
against — that is grading your own homework and voids soai's "verified" claim.

- **Tech Lead** owns the contract shape (`statement` + signature/types).
- **QA** authors the concrete examples / edge cases.
- **MVP collapse:** one role (Tech Lead) may do both; split later if test
  quality is poor. The invariant that matters is *test authorship ≠
  implementation*, not the number of roles.

### D2 — soai is a passive registry; it does not judge complexity

"Reject due to complexity" is **not** soai's job — it has no basis to judge and
adding orchestration muddies its one responsibility. Complexity is detected in
two honest places instead:

- **Pre-filter (Daedalus):** if you can't write the test cases, the task isn't
  decomposed enough. Inability to specify a test *is* the complexity detector,
  for free.
- **Empirical (AIOrchestra):** if it can't get tests green within budget, bounce
  back as `needs-decomposition`.

### D3 — The composer sits between submission and implementation

AIOrchestra's virtue is determinism. Creative retrieval ("what could I compose
here?") must not live in it, or runs become non-reproducible. The composer (a
Daedalus role) does the soai search and bakes the results into the issue body.
Auditability falls out for free: the issue records exactly what context the
implementer had.

### D4 — Composition references are explicit *(DECIDED — soai PR #7)*

A solution that uses other soai solutions declares them by ID, across the whole
lifecycle (candidate IDs at handoff → declared-used at submission → recorded as
dependency edges at publish). This is the one piece already written down, in
`soai/docs/solution-contract.md` ("Decided: composition references are
explicit") and cross-referenced from `data-model.md`. It is what makes soai a
DAG rather than a pile of snippets.

### D5 — The assurance ladder; record a `verification_level` per solution

Don't pick one verification strength globally. Record how high each solution
climbed:

| Level | Tool (Python) | Guarantee |
|---|---|---|
| `examples` | pytest | correct on the cases QA thought of |
| `properties` | **Hypothesis** | properties hold over generated inputs |
| `contracts` | deal / icontract | pre/postconditions checked each run |
| `symbolic` | **CrossHair** | contracts symbolically proven / counterexample |
| `proven` | **Dafny** | implementation provably meets spec |

soai's solution class (pure, typed, deterministic, no I/O) is the *ideal
habitat* for property-based testing and symbolic checking. Hypothesis is the
single best near-term upgrade: properties are closer to a contract than
examples and far harder for an implementer to overfit. Dafny is a real but
expensive rung — it moves the bottleneck from writing code to writing specs
(and a wrong spec verifies a wrong program); keep it *available*, not the path.

### D6 — Three-tier rule hierarchy, mirroring AIOrchestra's config merge

AIOrchestra already merges config in three layers (defaults → repo config →
explicit). The rule system mirrors it, one author per tier:

1. **Global baseline** — the opinionated default set (see Baseline below).
2. **Repo overrides** — written once by Daedalus DevOps at repo init, into the
   currently-empty `.aiorchestra/` repo-config slot.
3. **Task constraints** — in the issue body, written by the composer.

### D7 — Hard gates vs. soft signals (one taxonomy, three surfaces)

The same two-tier split already in soai's contract and AIOrchestra's semgrep
tiers governs the whole line. A *handful* of gates **block** (ruff, mypy,
pytest, secrets, high-severity security); everything else is **advisory** and
feeds the dialectical review and the refactor trigger rather than failing the
build. This prevents "gate sprawl" — a dozen blocking tools producing slow,
contradictory, noise that an implementer thrashes against.

## The repo-init baseline (Daedalus DevOps owns it)

Crossing the line currently written in Daedalus's brief ("Repo auto-creation:
out of scope"). When a user brings a request, Daedalus creates the repo and
stamps it with opinionated best practices. **The content is not invented — it
is the universal subset of AIOrchestra's own configuration**, so generated
repos are shaped like the repos AIOrchestra already knows how to operate on.
Scaffolder and enforcer must not drift.

**Scaffold ≠ environment.** Two lifecycles, do not conflate:

- **Scaffold** (once, committed, permanent): config, CI, rules, layout.
- **Environment** (every clone, never committed): `.venv`, installed deps —
  already handled by `aiorchestra/stages/prepare.py`. `.venv` is NOT init.

**Deterministic baseline vs. LLM layer.** The baseline is mechanical (ideally a
GitHub **template repo** — on-thesis, versioned, reviewable). Only
architecture-specific files (Dockerfile, deploy config, framework choice) come
from the LLM DevOps employee reading `architecture.md`.

### Baseline checklist

**A. Repo existence (deterministic)**
- create the repo; `.gitignore`, `LICENSE`, `README` skeleton
- AIOrchestra labels — *already built* (`aiorchestra setup-labels`)
- **branch protection: require CI green to merge** ← the keystone. Without it,
  every gate is advisory and the implementer can merge red.

**B. The opinionated baseline (deterministic; harvested from AIOrchestra)**
- `pyproject.toml` with `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest]`,
  `[tool.bandit]`
- `.semgrep/` — the **universal** subset of AIOrchestra's rules. Drop the
  project-specific ones (`run_command`, `aiorchestra.ai` imports, `_deep_merge`).
  Keep the *Tier 2b: Anti-shortcut Guards* — they apply to any AI-written
  Python (see "AI-smell pack" below).
- `.github/workflows/ci.yml` — the gate set
- `CLAUDE.md` — house rules (the prose half of every rule)
- `.aiorchestra/` repo config — fills the middle config-merge layer (D6)
- `src/` + `tests/` layout
- a standard `setup_logging` (structured: structlog, with coloredlogs for dev)

**C. Architecture-specific (LLM — existing DevOps employee)**
- Dockerfile, deploy config, framework files — genuinely vary per project.

### Toolchain — curate, don't pile on

"Tooling over rules" applied reflexively: modern **ruff** already subsumes most
of pylint (`PL`) and radon's cyclomatic complexity (`C901`). Running all three
means duplicate noise, slower CI, three configs to reconcile. Non-overlapping
set:

- **ruff** — lint + format + import sort + complexity + many pylint/security rules
- **mypy `--strict`** — types ruff can't do (strict so `Any` can't dodge them)
- **vulture** — dead code, as a **hard gate** (unused code = red, not a warning)
- **bandit / semgrep / pip-audit / gitleaks** — code / patterns / dependency
  CVEs / secrets (four different surfaces; the existing 5-prefix
  `no-hardcoded-secrets` regex is upgraded to gitleaks)
- **pytest + coverage + mutation testing** — correctness

Drop pylint and radon unless a specific check ruff lacks is found.

### "Best code never written" — operationalized

The headline principle is four mechanisms, not one:
- *reused* → soai search-first (the composer);
- *not duplicated* → soai's precedence rule (no stdlib re-wraps);
- *deleted* → vulture as a hard gate (the missing piece — dead code is a build
  error);
- *not grown* → complexity budget.

### The AI-smell pack (mostly already built)

AIOrchestra's `.semgrep/aiorchestra.yaml` already has a *"Tier 2b: Anti-shortcut
Guards"* section that catches classic AI failure modes as errors. Generalize and
ship it in every repo:
- `try: import X except ImportError` → already ERROR (also a CLAUDE.md rule)
- blanket `# noqa` / `# type: ignore` → already flagged
- **fixing tests instead of the issue** → not statically catchable. Defense is
  **(a)** make test files protected/read-only to the implementer, and **(b)**
  **mutation testing** — coverage proves a line ran; mutation proves an
  assertion would catch a bug. This is the only thing that catches
  assertion-free "green" tests.
- **mocking the thing under test** → see D8.

### D8 — Prefer real over fake; mock is the last resort

Functions, structures, and modules **must not be mocked** unless mocking is the
only way to test. Acceptable, in order of preference: exercise the real thing; a
local copy or derived dataset from real data; synthetic/fake data *when the
generator encodes genuine understanding of the domain*. Mocking internal
collaborators is an AI tell that produces vacuously-passing tests (it pairs with
the "fixing tests" smell). Candidate gate: flag `unittest.mock` / `MagicMock` /
`@patch` on internal modules outside a small allowlist (e.g. true external
boundaries — network, paid APIs, the clock). This complements mutation testing:
mutation catches tests that don't assert; the no-mock rule catches tests that
assert against a fake.

## New build items surfaced this session

### `aiorchestra setup` (command)

A single command that makes an existing repo AIOrchestra-ready, complementing
Daedalus's scaffold. Composes existing pieces plus new checks:
- `setup-labels` (exists)
- write/refresh the `.aiorchestra/` repo config
- verify the gate set is runnable in the working copy (`prepare.py` env)
- **the soai connection test** (below)
Must be **idempotent** — safe to re-run (consistent with ADR-002's init rule and
with baseline re-application across many repos).

### soai connection test (preflight)

AIOrchestra both *reads* soai (issues reference candidate solution IDs to
compose) and *writes* soai (publish posts solutions back). Before a run, a
preflight must verify: soai is reachable, and any solution IDs referenced in the
issue resolve. Model it on the existing provider `available()` pattern. A failed
preflight is a clean "can't start," not a mid-run crash.

## Ad-hoc capture → soai (open mechanism, agreed intent)

When an agent writes throwaway Python to compute something, that code has value
and should not be lost — **but it must not be registered directly**, which would
violate soai's precedence rule and poison search with unverified, trivial
entries. Two stages:

- **Capture log** — cheap, append-only, everything that ran. Provenance.
- **Registry** — curated, verified, non-trivial, typed. Promotion only.

The owner's key refinement: **a captured snippet becomes registerable only once
its "problem" is stated.** Naming the problem an ad-hoc solves is the act that
creates value — it turns a fragment into a reusable answer to a recurring need,
and frequently-captured-but-unregistered problems become soai's demand signal
for what to build next. Exact mechanism TBD; the capture log is the agreed
starting point.

## Already built (so we don't rebuild it)

- AIOrchestra env setup: clone + `.venv` + deps — `stages/prepare.py`
  (switch pip → **uv** for speed + a lockfile, which is currently missing).
- AIOrchestra labels — `aiorchestra setup-labels`.
- Anti-shortcut semgrep guards — `.semgrep/aiorchestra.yaml` Tier 2b.
- Tiered gates (ERROR/WARNING/INFO) — same file.
- Refactor trigger at 10 merged PRs — `.github/workflows/refactor-trigger.yml`.
- Cross-model review seed — `templates/review_cross_model.md`.
- Observability (Sentry + Langfuse, free-tier, gated) — ADR-002.
- Daedalus DevOps employee that writes CI/Dockerfiles from architecture.
- soai composition-references decision — soai PR #7.

## Open questions

1. Baseline home: a GitHub **template repo** vs. a `templates/` dir copied in.
   (Leaning template repo — first-class, reviewable, keeps init logic tiny.)
2. Dialectical review home: CI job (blocking) vs. Claude Code hooks (local,
   advisory, bypassable). Leaning: blocking → CI; fast feedback → hooks.
3. Capture-log mechanism and the promotion gate (D-ad-hoc).
4. soai `Problem` needs a `tests`/`examples` field — first concrete schema
   change the whole plan depends on.
5. `verification_level` field on soai `Solution` (D5).
6. Two solution classes (pure deterministic vs. probabilistic/LLM) — soai's
   still-open contract fork; LLM-invoking modules don't fit v1's exact oracle.
7. Baseline versioning: stamp each repo with the baseline version it used; make
   init idempotently re-appliable to roll updates across N repos.

## Consequences

**Positive**
- One coherent system instead of three orphans; each does what it is shaped for.
- Quality is enforced where it's real (CI), authored where it's owned (one
  author per rule tier), and never depends on an agent "remembering" a prompt.
- Reuse compounds: every published solution makes the next request cheaper.

**Negative / costs**
- Real coupling across three repos; contracts (issue schema, solution payload,
  problem schema) must be versioned deliberately.
- soai's weak text-search recall means duplicate problems early (acceptable for
  MVP; embedding search is roadmapped).
- The line only pays off for genuinely reusable, function-shaped work. Don't
  force project-specific tasks (a landing page) through the soai detour.

## Rollout (no code in this ADR)

1. Land this ADR.
2. soai schema: add `tests`/`examples` to `Problem`; `verification_level` to
   `Solution`. (Open questions 4–5.)
3. Harvest AIOrchestra's `.semgrep` Tier 2b + tool configs into a candidate
   baseline pack; decide the baseline home (open question 1).
4. Daedalus: composer step + DevOps repo-init capability.
5. AIOrchestra: `setup` command + soai connection preflight; treat embedded
   issue tests as immutable; publish-back to soai.
</content>
</invoke>
