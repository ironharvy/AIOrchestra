# Evaluation: Additional Code Quality Tools for AIOrchestra

**Date:** 2026-04-09
**Status:** Proposal

## Context

AIOrchestra validates code it produces through a shell-based validation pipeline
(validate stage). The current tooling stack is:

| Tool | Purpose | CI Job |
|------|---------|--------|
| Ruff | Linting + formatting | `lint` |
| Bandit | Security pattern matching | `security` |
| Semgrep | 11 custom domain-specific rules | `security` |
| pytest | Test execution (no coverage) | `test` |

**Gaps identified:** no type checking, no coverage gates, no complexity metrics,
no dead code detection, no dependency vulnerability scanning, no test quality
enforcement.

This evaluation covers tools for two use cases:
1. **Self** — checking AIOrchestra's own codebase in CI
2. **Generated** — checking code that AIOrchestra produces via AI agents

---

## 1. Type Correctness

### Recommendation: **Pyright (basic mode)**

| Tool | License | Speed | Gradual Typing | String API | Status |
|------|---------|-------|-----------------|------------|--------|
| **Pyright** | MIT | Fast (Node/TS) | Best-in-class (`basic`/`standard`/`strict`) | No (files) | Active |
| mypy | MIT | Slower (Python) | Good (per-module overrides) | No (files) | Active |
| ty (Astral) | MIT | Fastest (Rust) | TBD | TBD | Beta — not production-ready |
| pytype (Google) | Apache-2.0 | Slow | Good | No | **Deprecated** (Python 3.12 last) |

**Why Pyright over mypy:**
- AIOrchestra has ~34% type annotation coverage — Pyright's `basic` mode
  produces useful results on partially-typed code without drowning in noise.
- 2-5x faster than mypy.
- No Python-side dependencies (ships as a pip-installable Node bundle).
- Ruff docs explicitly recommend pairing with Pyright.

**Future:** Reassess `ty` (by the ruff/Astral team) once it reaches stable
(expected late 2026). Its ruff integration will be a natural fit.

**Integration:**
```toml
# pyproject.toml
[tool.pyright]
typeCheckingMode = "basic"
pythonVersion = "3.10"
```
```yaml
# CI: add to lint job
- run: pip install pyright && pyright
```

**For generated code:** Write AI output to temp files, run `pyright --outputjson`
on them, parse results as validation feedback.

---

## 2. Deep Static Analysis (Code Smells, Complexity, Architecture)

### Recommendation: **Pylint (refactoring checks) + Vulture (dead code)**

| Tool | License | What it adds over Ruff | String API | Status |
|------|---------|------------------------|------------|--------|
| **Pylint** | GPLv2 | ~200 rules Ruff lacks: type inference, refactoring smells (too-many-args, too-many-branches, duplicate code) | No (files) | Active |
| **Vulture** | MIT | Unused functions/classes/variables across project (Ruff only catches unused imports) | No (files) | Active |
| Prospector | GPLv2 | Wrapper around Pylint+others — adds indirection, no unique value | No | Active but redundant |

**Why not Prospector:** It just bundles tools we'd configure individually. The
wrapper adds config complexity without adding detection capabilities.

**Pylint integration:**
```toml
# pyproject.toml
[tool.pylint.messages_control]
disable = [
    "C0114", "C0115", "C0116",  # missing docstrings (not enforced)
    "R0903",                     # too-few-public-methods (dataclasses)
]

[tool.pylint.format]
max-line-length = 100
```
```yaml
# CI: add as separate job (10-50x slower than Ruff)
- run: pip install pylint && pylint aiorchestra/
```

**Vulture integration:**
```yaml
# CI: fast, add alongside Pylint
- run: pip install vulture && vulture aiorchestra/ --min-confidence 80
```

**For generated code:** Both require files on disk — write to temp dir, run,
capture output. Particularly valuable for AI-generated code which often includes
dead code.

---

## 3. Code Metrics & Maintainability

### Recommendation: **Radon (programmatic) + Xenon (CI gate)**

| Tool | License | Metrics | String API | Status |
|------|---------|---------|------------|--------|
| **Radon** | MIT | Cyclomatic complexity (A-F), maintainability index, Halstead metrics | **Yes** (`cc_visit(code_string)`) | Stable (low-churn) |
| **Xenon** | MIT | Threshold gate over Radon | No (CLI only) | Stable |
| Wily | Apache-2.0 | Complexity trends over git history | No | Inactive |
| Lizard | MIT | CC, NLOC, copy-paste detection (15 languages) | Yes (`analyze_source_code`) | Active |

**Why Radon is uniquely valuable:** It is the only tool evaluated with a
programmatic API that operates directly on code strings. This means AIOrchestra
can score AI-generated code *in-memory* during the validate stage, before
writing anything to disk:

```python
from radon.complexity import cc_visit
from radon.metrics import mi_visit

blocks = cc_visit(generated_code)
high_complexity = [b for b in blocks if b.complexity > 10]  # Grade C+

mi_score = mi_visit(generated_code, multi=True)  # 0-100
```

**CI gate with Xenon:**
```yaml
# Fail if any function exceeds complexity C (>10), module average exceeds B (>5)
- run: pip install xenon && xenon --max-absolute C --max-average B aiorchestra/
```

**For generated code:** Radon's string API makes it ideal for in-process
validation. This is the strongest candidate for integration into the validate
stage itself (not just CI).

---

## 4. Test Quality

### Recommendation: **Tiered adoption**

| Priority | Tool | Problem Solved | Overhead | Status |
|----------|------|----------------|----------|--------|
| **P0** | pytest-cov | Coverage measurement + branch coverage + min threshold | ~5-10% slowdown | Active |
| **P0** | pytest-timeout | Prevent CI hangs (critical for subprocess-heavy tests) | None | Active |
| **P1** | pytest-randomly | Expose hidden inter-test dependencies | None | Active |
| **P2** | hypothesis | Property-based testing (ideal for `_deep_merge()`, config logic) | Moderate (configurable) | Active |
| **P3** | pytest-xdist | Parallel execution (value grows with suite size) | ~1-2s startup | Active |
| **P4** | mutmut | Mutation testing — validates test effectiveness | High (10-30min) | Active |

**Integration:**
```toml
# pyproject.toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "pytest-timeout>=2.0",
    "pytest-randomly>=3.0",
    "ruff>=0.4",
    "bandit>=1.7",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
timeout = 30
addopts = "--cov=aiorchestra --cov-branch --cov-fail-under=80 -p randomly"
```

**mutmut** should run nightly/weekly, not per-PR:
```yaml
# Separate CI workflow on schedule
- run: pip install mutmut && mutmut run --paths-to-mutate=aiorchestra/
```

---

## 5. SonarQube / Security Taint Analysis

### Recommendation: **Skip SonarQube, add pip-audit, evaluate Pysa**

| Tool | License | Verdict | Reason |
|------|---------|---------|--------|
| SonarQube Community | LGPL | **Skip** | Requires self-hosted server (Java/PostgreSQL). Free tier lacks branch analysis and PR decoration. High overlap with existing ruff+bandit+semgrep. |
| SonarCloud | Free for OSS | **Maybe** | If repo is public, low-effort to add. Provides dashboard and duplication detection. But mostly redundant. |
| PyT | GPLv2 | **Skip** | **Abandoned** since March 2018. Only targeted Flask. |
| **pip-audit** | Apache-2.0 | **Add** | Zero overlap with existing tools. Scans dependencies against PyPA Advisory DB. Catches a real blind spot. |
| Pysa (Meta) | MIT | **Evaluate** | True taint analysis (source-to-sink data flow). Relevant since AIOrchestra routes issue content through `run_command()`. Has a GitHub Action. |

**pip-audit integration:**
```yaml
# CI: add to security job
- run: pip install pip-audit && pip-audit
```

**Pysa** is worth evaluating separately — it requires Pyre type checker
infrastructure and is a larger commitment. However, for a project that passes
user-influenced data (GitHub issue content) into shell commands, taint tracking
is architecturally relevant.

---

## Summary: Recommended Adoption Plan

### Phase 1 — Quick wins (low effort, high value)

| Tool | Use Case | Where |
|------|----------|-------|
| pytest-cov (80% threshold) | Coverage gates | CI `test` job |
| pytest-timeout (30s) | Prevent CI hangs | CI `test` job |
| pytest-randomly | Test isolation | CI `test` job |
| pip-audit | Dependency vulnerabilities | CI `security` job |
| Xenon | Complexity gate | CI `lint` job |

### Phase 2 — Type safety & deeper analysis

| Tool | Use Case | Where |
|------|----------|-------|
| Pyright (basic mode) | Type correctness | CI `lint` job |
| Vulture (80% confidence) | Dead code detection | CI `lint` job |
| Radon (programmatic) | Score generated code in-memory | Validate stage |

### Phase 3 — Advanced quality

| Tool | Use Case | Where |
|------|----------|-------|
| Pylint (R-category focus) | Deep code smell detection | CI separate job |
| hypothesis | Property-based tests for config/templates | Test suite |
| mutmut | Mutation testing | Nightly CI |

### Deferred

| Tool | Reason |
|------|--------|
| ty (Astral) | Still in beta; reassess late 2026 |
| SonarQube | Operational overhead not justified with current stack |
| Pysa | Requires Pyre infrastructure; evaluate as a separate spike |
| PyT | Abandoned |
| Prospector | Redundant wrapper |
| Wily | Complexity trends are nice-to-have, not critical |
