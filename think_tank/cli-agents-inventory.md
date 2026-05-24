# CLI Coding Agents — Inventory & Candidates

**Status:** Survey (no decision)
**Date:** 2026-05-24
**Author:** AI evaluation

## Purpose

Track the landscape of terminal/CLI coding agents so we can decide which to
add as providers. This is an inventory, not an ADR — adding any of these is a
follow-up decision per agent.

## Implementation status (2026-05-24)

Priority set by maintainer: **(1) Antigravity, (2) Cursor, (3) Freebuff**;
**Aider** added afterwards.

| Agent | Provider id | Binary | Status |
|---|---|---|---|
| Antigravity CLI | `antigravity` | `agy` | **Added** — `_antigravity.py`, registry, tests |
| Cursor CLI | `cursor` | `cursor-agent` | **Added** — `_cursor.py`, registry, tests |
| Aider | `aider` | `aider` | **Added** — `_aider.py`, registry, tests; auto-commit disabled by default (see Tier 2) |
| Freebuff | — | `freebuff` | **Skipped** — no documented non-interactive mode + self-downloading npm stub (see below) |

All new providers extend `CLIProvider` and add no Python runtime deps.
Note: `antigravity` is added as a **new** provider; the Gemini-CLI retirement
migration (below) remains a separate open item — Gemini stays for now and will
be removed eventually (maintainer decision, 2026-05-24).

## Currently supported

From `aiorchestra/ai/_registry.py` and `_agents.py`:

| Provider id | Family | Base class | Binary |
|---|---|---|---|
| `claude-code` | claude | `CLIProvider` | `claude` |
| `codex` | codex | `CLIProvider` | `codex` |
| `gemini` | gemini | `CLIProvider` | `gemini` |
| `jules` | jules | (Jules) | — |
| `ollama` | — | (Ollama) | `ollama` |
| `opencode` | opencode | `CLIProvider` | `opencode` |

## Candidate fit criteria

A CLI agent is a clean fit for the existing `CLIProvider` base
(`aiorchestra/ai/_cli.py`) when it has:

1. A binary discoverable via `shutil.which()`.
2. A **non-interactive / print / exec** mode: prompt in → result on stdout,
   exit code signals success.
3. A way to auto-approve tool use (no interactive confirmation prompts).

All candidates below shell out to an external CLI, so none add a new Python
runtime dependency — no ADR required per CLAUDE.md ("No new runtime
dependencies without an ADR"). Each still needs its own `_<provider>.py`,
registry + `__init__` wiring, an `available()` check, and tests.

## Tier 1 — explicitly requested

| Tool | Maker | OSS? | Binary | Non-interactive invoke | Notes |
|---|---|---|---|---|---|
| **Cursor CLI** | Cursor (Anysphere) | proprietary | `cursor-agent` | `cursor-agent -p "…"` | Clean print mode for CI. Reads `AGENTS.md`/`CLAUDE.md` + `.cursor/rules`, supports MCP. Install: `curl https://cursor.com/install -fsSL \| bash`. Beta. |
| **Grok Build** (official) | xAI | proprietary | `grok` | plan/exec mode (confirm flag) | **Gated**: SuperGrok Heavy (~$300/mo) at time of writing. Install: `curl -fsSL https://x.ai/cli/install.sh \| bash`. Subagents, Grok 4.3 beta, 2M ctx. |
| **grok-cli** (community alt) | superagent-ai / vibe-kit | OSS (MIT) | `grok` | `grok --prompt "…"` | Unaffiliated with xAI; thin wrapper over the Grok API. Not gated — easier first integration than official Grok Build. `npm @vibe-kit/grok-cli`. |
| **Codebuff / Freebuff** | CodebuffAI | OSS | `codebuff` / `freebuff` | **none documented** (interactive TUI only) | "freebuff" = free, **ad-supported** edition (text ads printed in CLI). Multi-subagent. Defaults to DeepSeek/Kimi/MiniMax. `npm i -g freebuff`. **Blocker:** both the Freebuff and Codebuff READMEs document only the interactive TUI — no `-p`/`--print`/`run`/`exec` one-shot flag — so it does not fit `CLIProvider`. A programmatic path exists via the `@codebuff/sdk` (TypeScript), which is a different integration shape than shelling out to a binary. |

## Tier 2 — high-priority, well-established (non-interactive mode exists)

| Tool | Maker | OSS? | Binary | Non-interactive invoke | Notes |
|---|---|---|---|---|---|
| **Aider** | Aider-AI | OSS | `aider` | `aider --message "…" --yes-always` | **Added.** The original terminal pair-programmer. Differs from the others: it auto-commits to git by default. Our provider disables that (`--no-auto-commits --no-dirty-commits`) so the `publish` stage owns committing; set `auto_commits: true` to opt back in. Also uses `--no-pretty --no-stream` for clean stdout. Model-agnostic. |
| **Goose** | Block | OSS (Apache-2) | `goose` | `goose run -t "…"` | MCP-native from day one; model-agnostic. |
| **Crush** | Charmbracelet | OSS (Go) | `crush` | `crush run "…"` | TUI-first, LSP-enhanced, mid-session model switching. |
| **Amp** | Sourcegraph | proprietary | `amp` | `amp -x "…"` | npm `@sourcegraph/amp`. "Deep mode" extended reasoning. CLI rebuilt 2026. |
| **Qwen Code** | Alibaba / QwenLM | OSS | `qwen` | `qwen -p "…"` | Gemini-CLI fork tuned for Qwen models; OpenAI/Anthropic/Gemini-compatible APIs. |
| **Continue CLI** | Continue | OSS | `cn` | `cn -p "…"` | Headless mode; multi-model. |
| **GitHub Copilot CLI** | GitHub | proprietary | `copilot` | `copilot -p "…"` | PR/issue workflows, headless automation. |
| **Droid** | Factory | proprietary | `droid` | `droid exec "…"` | Reported #1 on Terminal-Bench; specialized subagents. |

## Tier 3 — secondary / niche (worth tracking)

| Tool | Maker | OSS? | Binary | Notes |
|---|---|---|---|---|
| **OpenHands CLI** | All-Hands-AI | OSS | `openhands` | Ex-OpenDevin; agentic dev env, headless mode. |
| **Plandex** | Plandex | OSS | `plandex` / `pdx` | Plan-first multi-file development. |
| **Forge (ForgeCode)** | antinomyhq | OSS | `forge` | 300+ models via your own keys. |
| **SWE-agent** | Princeton | OSS | `sweagent` | Optimized for repo issue resolution (SWE-bench). |
| **Open Interpreter** | OpenInterpreter | OSS | `interpreter` | General autonomous code/command execution. |
| **Cline CLI** | Cline | OSS | `cline` | Model-agnostic autonomous planning. |
| **Roo Code CLI** | Roo | OSS | `roo` | Multi-mode (architect/code/debug/orchestrator). |
| **Mistral (Vibe) CLI** | Mistral | proprietary | `mistral`/`vibe` | Conversational repo edits. Confirm binary + non-interactive flag. |
| **Warp** | Warp | proprietary | `warp` | Agent mode inside the Warp terminal; less of a scriptable CLI. |

## ⚠️ Affects an existing provider: Gemini CLI → Antigravity CLI

Multiple sources report Google **retired Gemini CLI at I/O on 2026-05-19** and
replaced it with **Antigravity CLI** (part of Antigravity 2.0). Gemini CLI
reportedly **stops serving free/Pro/Ultra accounts on 2026-06-18**.

Action: our existing `gemini` provider (binary `gemini`) likely needs to
migrate to the `agy` (Antigravity) binary before that date. Track this
**separately** from the "add new agents" work — it is maintenance of a shipped
provider, not a new addition. Note the new `antigravity` provider added in this
branch is a *distinct* entry; it does not retire or replace `gemini`.

## Sourcing caveats

The largest aggregator surveyed (`bradAGI/awesome-cli-coding-agents`) also
lists an "OpenClaw / Claw Code / ZeroClaw / NullClaw / PicoClaw" cluster with
very large star counts. These could not be independently verified and may be
list padding — **confirm independently before treating any as real**. They are
deliberately excluded from the tiers above.

Tool details (binaries, flags, gating, pricing) change fast in this space;
re-verify each candidate's non-interactive invocation and auth model at
implementation time.

## Suggested next steps

1. **Done:** Antigravity, Cursor, Aider providers added.
2. Remaining easy win with a clean non-interactive mode: **Goose**
   (`goose run -t "…"`).
3. For Grok, start with the community **grok-cli** (not gated) rather than
   official Grok Build.
4. Keep the **Gemini → Antigravity** retirement as a separate future task
   (Gemini stays for now).
5. For each chosen agent, follow the "Adding new AI providers" checklist in
   CLAUDE.md (`_<provider>.py` → registry → `__init__` → `available()` →
   tests).
