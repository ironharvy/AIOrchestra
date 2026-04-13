# ADR-001: Evaluate Dagger.io for AIOrchestra

**Status:** Rejected  
**Date:** 2026-04-09  
**Author:** AI evaluation  

## Context

[Dagger.io](https://dagger.io/) is a programmable CI/CD engine that runs
pipelines inside containers. It replaces YAML-based CI definitions with real
code (Go, Python, TypeScript), backed by a custom BuildKit-derived engine that
schedules work as a DAG and provides content-addressed caching.

This ADR evaluates whether adopting Dagger would benefit AIOrchestra — an agent
orchestration framework that processes GitHub issues through discover →
implement → validate → review → publish stages.

## Dagger Overview

| Aspect | Detail |
|---|---|
| **Execution model** | Every pipeline step runs in an OCI container, orchestrated by the Dagger Engine (a custom BuildKit fork). |
| **SDK** | Python SDK (`dagger-io` on PyPI, requires Python ≥3.10). |
| **DAG scheduling** | Operations form a directed acyclic graph; independent steps run concurrently; caching is content-addressed. |
| **Observability** | Full OpenTelemetry traces, granular logs and metrics per operation. |
| **Reuse** | Pipeline functions can be packaged as "modules" and shared via the Daggerverse registry. |
| **Requirements** | Container runtime (Docker/Podman). Engine runs in a privileged container. |

## Evaluation Against AIOrchestra

### Where Dagger Could Help

1. **Reproducible validation containers.** The `validate` stage
   (`aiorchestra/stages/validate.py`) runs `ruff`, `pytest`, `bandit`, and
   `semgrep` on the host. Dagger could lock these tools into a container image,
   eliminating "works on my machine" drift between local runs and CI.

2. **Parallel stage execution.** Dagger's DAG engine can automatically
   parallelize independent operations. Today, AIOrchestra runs lint, tests, and
   static analysis sequentially within `validate()`. Dagger could run them
   concurrently with built-in caching.

3. **Environment preparation isolation.** The `prepare` stage
   (`aiorchestra/stages/prepare.py`) clones repos, creates venvs, and installs
   deps directly on the host. Dagger could isolate each target repo's
   environment in a container, preventing dependency conflicts across
   concurrent issue pipelines.

4. **Caching.** Repeated `pip install` and `git clone` operations could benefit
   from Dagger's content-addressed cache layers, especially during retry loops.

### Why It Doesn't Fit

1. **Architecture mismatch — AIOrchestra is an agent orchestrator, not a build
   pipeline.** Dagger is designed for deterministic build/test/deploy tasks.
   AIOrchestra's core loop invokes AI agents (Claude Code, Codex, Gemini) that
   produce unpredictable output, need filesystem access to the target repo,
   perform multi-turn interactions, and run for minutes. These long-lived,
   stateful, non-deterministic processes are fundamentally different from what
   Dagger's container-per-step model is optimized for.

2. **AI providers need host access.** All six AI providers in
   `aiorchestra/ai/` invoke CLI tools (`claude`, `codex`, `gemini`,
   `opencode`) or local HTTP servers (`ollama`). These CLIs need access to the
   user's auth tokens, filesystem, network, and often interactive TTY
   capabilities. Containerizing them requires mounting credentials, host
   networking, and possibly privileged mode — negating the isolation benefits.

3. **`os.fork()` parallelism already works.** AIOrchestra parallelizes issue
   processing via `os.fork()` in `pipeline.py:151-186`. This is lightweight
   and allows each child to share the parent's environment. Replacing this with
   Dagger containers adds startup overhead, image pull latency, and complexity
   without clear throughput gains for this workload.

4. **Minimal dependency philosophy.** AIOrchestra has exactly one runtime
   dependency: `pyyaml`. Adding Dagger introduces the `dagger-io` SDK, a
   mandatory Docker daemon, and the Dagger Engine (privileged container). This
   triples the infrastructure requirements for a tool that currently runs
   anywhere Python is installed.

5. **Caching ROI is low.** AIOrchestra's bottleneck is AI invocation time
   (minutes per call), not build/install time. The validation stage takes
   seconds. Dagger's sophisticated caching provides marginal improvement where
   it doesn't matter.

6. **Debugging complexity.** Dagger abstracts logs behind its engine. Multiple
   reviewers report that debugging failures inside Dagger containers is harder
   than reading direct subprocess output. AIOrchestra's current `_shell.py`
   gives clean, immediate stdout/stderr — easier to feed back into AI retry
   loops.

7. **Privileged container requirement.** The Dagger Engine must run in a
   privileged container. In hosted CI environments or locked-down servers, this
   is a non-starter. AIOrchestra currently runs unprivileged.

### Cost-Benefit Summary

| Benefit | Without Dagger | With Dagger | Delta |
|---|---|---|---|
| Reproducible validation env | Host tools, CI matches local | Containerized tools | Marginal — CI already uses same image |
| Parallel validation steps | Sequential (~seconds) | DAG-parallel (~seconds) | Negligible for fast checks |
| Dep isolation | venv per repo | Container per repo | Modest — venvs already isolate |
| Caching | pip cache, git fetch | Content-addressed layers | Low — bottleneck is AI, not builds |
| **New complexity** | — | Docker daemon, privileged engine, SDK, container networking | **Significant** |
| **New failure modes** | — | Engine crashes, image pulls, cache invalidation, credential mounting | **Significant** |

## Decision

**Reject Dagger adoption.** The complexity cost exceeds the benefits for
AIOrchestra's workload. The project's pipeline is an *agent orchestrator*
managing long-lived AI invocations, not a *build system* running deterministic
container steps.

## Alternatives Considered

- **Do nothing (chosen).** The current architecture — subprocess-based stages
  with `os.fork()` parallelism — is simple, fast, and matches the workload.
- **Containerize just the validation stage.** If reproducibility becomes a real
  problem, a simple `docker run` in `validate.py` achieves isolation without
  the full Dagger stack. This is worth revisiting if host-tool drift causes
  actual failures.
- **Use Dagger only in CI (not in the orchestrator).** Replace
  `.github/workflows/ci.yml` with a Dagger pipeline for AIOrchestra's own CI.
  This is viable but low priority — the current 50-line workflow is simple and
  works.

## References

- [Dagger.io](https://dagger.io/)
- [Dagger Python SDK](https://pypi.org/project/dagger-io/)
- [Dagger Engine architecture](https://deepwiki.com/dagger/dagger/1.2-architecture-overview)
- [Real-world review](https://medium.com/@frank.ittermann_46267/part-2-my-journey-with-dagger-io-almost-perfect-but-not-quite-2bb3b645e938)
