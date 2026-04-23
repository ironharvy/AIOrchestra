# AIOrchestra

A lightweight, always-running orchestrator that watches for GitHub issues and drives AI coding agents with deterministic shell automation. Start it on your home machine, walk away — when you file an issue from a plane hours later, it picks it up, implements, tests, and opens a PR. Instead of burning tokens on git commands and test runs, AIOrchestra handles the predictable work and only invokes the AI when intelligence is actually needed.

## How it works

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Discover    │────▶│  Prepare    │────▶│  OSINT       │────▶│  Implement   │
│  (gh/shell)  │     │  (git/sh)   │     │  (shell/LLM) │     │  (AI agent)  │
└─────────────┘     └─────────────┘     └──────────────┘     └──────┬───────┘
      ▲                                                             │
      │                                        ┌────────────────────┤
      │  ┌──────────────────┐           on ambiguity          on success
      │  │  Clarification   │◀──────────────────┘                   │
      │  │  (comment+label) │                                ┌──────▼──────┐
      │  └──────┬───────────┘                                │  Validate   │
      │         │                                            │  (sh/tests) │
      │    defer issue                                       └──────┬──────┘
      └─── (skip next run)                                         │
                                               on failure ─────────┘
                                               re-invoke AI         │
                                                              on success
                    ┌─────────────┐     ┌─────────────┐     ┌──────▼──────┐
                    │  Review     │◀────│  CI Watch   │◀────│  Publish    │
                    │  (AI agent) │     │  (gh/poll)  │     │  (git/gh)   │
                    └──────┬──────┘     └──────┬──────┘     └─────────────┘
                           │                   │
                           └─── on failure ────┘──▶ re-invoke AI with context
```

### Pipeline stages

| Stage | What runs | AI? | Description |
|-------|-----------|-----|-------------|
| **Discover** | `gh issue list --label <label>` | No | Find issues tagged for automation, skip in-progress/deferred ones |
| **Prepare** | git clone/pull, checkout -b, venv setup | No | Set up a clean working environment |
| **OSINT** | whois, dig, curl + Ollama | Local | Gather external intelligence about targets in the issue |
| **Implement** | Claude Code CLI | Yes | Generate implementation from issue description + OSINT context |
| **Validate** | pytest, ruff | No | Run tests and linters locally |
| **Publish** | git push, gh pr create | No | Create PR and push changes |
| **CI Watch** | Poll `gh pr checks` | No | Wait for CI to pass |
| **Review** | Claude Code CLI | Yes | AI code review on the diff |
| **Clarification** | `gh issue comment` + label | No | Defer ambiguous issues with a question for the author |

On failure at Validate, CI, or Review — the AI is re-invoked with the error output appended to the prompt. A configurable retry cap prevents infinite loops.

### Stage contracts

What each stage consumes, does, and produces. Protocol types live in
`aiorchestra/stages/types.py`.

| Stage | Entry function | Intake | Produces | External side effects |
|-------|----------------|--------|----------|-----------------------|
| **Discover** | `discover_issues(repo, label, …)` / `discover_all_issues(owner, label, …)` | repo (or owner) + label, optional issue number | `list[IssueData]` (single repo) or `dict[repo → list[IssueData]]` (multi-repo); issues carrying any `SKIP_LABELS` are filtered out | Read-only `gh issue list` / `gh issue view` / `gh search issues` |
| **Prepare** | `prepare_environment(repo, branch, workspace)` | `owner/repo`, branch name, workspace root | Absolute path to the repo working copy, or `None` on failure | Clones/fetches repo into `~/.aiorchestra/workspaces/<repo>`, creates/checks out branch, sets up `.venv` and installs deps |
| **OSINT** | `enrich_issue(issue, osint_config)` | Issue + `osint` config block | `str` — OSINT context ready to splice into the implement prompt (empty when disabled or no targets) | Runs local CLI tools (`whois`, `dig`, `curl`, optionally `nmap`); hits a local Ollama endpoint for summarisation. No cloud tokens. |
| **Implement** | `implement(issue, config, prompt_name, error_text, repo_root, osint_context, repo)` | Issue, full pipeline config, OSINT context, optional error text from a prior failed attempt | `InvokeResult` — `success`, `stdout`, `stderr`, `returncode`, optional `clarification` parsed from a `NEEDS_CLARIFICATION:` marker | Spends cloud AI tokens; the AI agent edits files under `repo_root`. No git or GitHub calls. |
| **Validate** | `validate(config, repo_root)` | Pipeline config (reads `test.lint_command`, `test.command`, `review.tiers[static-analysis]`), working copy | `FeedbackResult` — `(passed: bool, feedback: str \| None)`; `feedback` is the combined lint/test/static-analysis error output used to prime the next implement retry | Runs lint/test/static-analysis tools (T0 + T1) on local files only |
| **Publish** | `publish(repo, branch, issue, repo_root, pr_url)` | `owner/repo`, branch, issue, working copy, optional existing PR URL | `PublishResult` — PR URL on success, `None` if the branch has no diff or push/PR creation fails | `git add -A`, `git commit`, `git push -u origin <branch>`, `gh pr create` / updates existing PR |
| **CI Watch** | `wait_for_ci(pr_url, config)` | PR URL, `ci` config (timeout, poll_interval) | `FeedbackResult` — `(passed, failure_logs)` | Polls `gh pr checks` until every check concludes or `ci.timeout` elapses. Read-only. |
| **Review** | `review(repo, branch, config, issue, repo_root)` | `review.tiers` config, diff vs. `origin/main`, issue metadata | `FeedbackResult` — short-circuits on the first failing tier; `feedback` feeds the `fix_review` prompt | T3 AI review (primary provider) and T4 cross-model review spend tokens; T5 human-required reads labels. No GitHub writes. |
| **Clarification** | `request_clarification(repo, issue, message)` | `owner/repo`, issue, question from the agent's `NEEDS_CLARIFICATION:` marker | `bool` — `True` only when both the comment and the label were applied | `gh issue comment` posts the question; `needs-clarification` label is added so discover skips the issue on future runs |

> `IssueData`, `FeedbackResult`, `PublishResult`, and the `Protocol` classes
> (`ImplementFn`, `ValidationFn`, `RemoteCheckFn`, `PublishFn`) are defined in
> [`aiorchestra/stages/types.py`](aiorchestra/stages/types.py). Label
> constants (`LABEL_WORKING`, `LABEL_NEEDS_CLARIFICATION`,
> `LABEL_AWAITING_REVIEW`, `LABEL_FAILED`) live in
> [`aiorchestra/stages/labels.py`](aiorchestra/stages/labels.py).

### Review tiers

The review stage runs ordered tiers and short-circuits on the first failure.
T0 and T1 execute earlier (in **Validate**), so the Review stage itself only
runs T3–T5:

| Tier | Name | Runs in | What it checks |
|------|------|---------|----------------|
| T0 | lint + tests | Validate | `test.lint_command`, `test.command` |
| T1 | `static-analysis` | Validate | Tools listed under `review.tiers[static-analysis].commands` (e.g. `semgrep`, `bandit`); missing tools on PATH are skipped |
| T3 | `ai-review` | Review | Primary AI reviews the diff vs. `origin/main` using the `review` template |
| T4 | `cross-model-review` / `cross-agent-review` | Review | A second provider cross-checks the diff; by default `pick_cross_agent()` picks a different family from the implementation provider |
| T5 | `human-required` | Review | Gate on a human-approval label; keeps the issue in the `awaiting-review` state |

### Agent clarification protocol

When the AI agent encounters an ambiguous or underspecified issue, it can signal this by emitting a `NEEDS_CLARIFICATION:` marker in its output instead of guessing:

```
NEEDS_CLARIFICATION: Should this endpoint return 404 or 204 when the collection is empty?
```

The pipeline detects this, posts the question as a comment on the GitHub issue, adds a `needs-clarification` label, and defers the issue. Future runs skip it until a human removes the label.

### Issue lifecycle labels

The pipeline uses GitHub labels to track issue state and prevent collisions
across concurrent runs. All four are defined as constants in
`aiorchestra/stages/labels.py` and are collectively the `SKIP_LABELS` set
that the discover stage filters out.

| Label | Meaning | Added | Removed |
|-------|---------|-------|---------|
| `agent-working` | An agent has claimed this issue | Before processing starts | On completion, failure, or deferral |
| `needs-clarification` | Waiting on human input | When the agent emits `NEEDS_CLARIFICATION:` | Manually, after the human responds |
| `awaiting-review` | Blocked on the T5 human-required review tier | When the review stage hits a `human-required` tier | Manually, when a reviewer approves |
| `agent-failed` | Pipeline terminated unsuccessfully | On unrecoverable failure (retries exhausted, publish error, …) | Manually, after investigation |

Discovery skips issues carrying any of these labels so concurrent runs
never double-claim the same issue.

### Parallel processing

By default, the pipeline forks a child process per issue so multiple issues are processed concurrently. The parent claims each issue (`agent-working` label), forks, and moves on. Each child runs the full pipeline for its issue and exits. Sequential mode is available via `parallel=False`.

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Run continuously — scan all your repos every 5 minutes
aiorchestra dispatch --watch

# Watch a single repo
aiorchestra run --repo owner/repo --label claude --watch

# Custom poll interval (seconds)
aiorchestra dispatch --watch --poll-interval 120

# One-shot: process all issues labeled "claude" in a repo
aiorchestra run --repo owner/repo --label claude

# One-shot: process a specific issue
aiorchestra run --repo owner/repo --issue 42

# Dry run — show what would happen without executing
aiorchestra run --repo owner/repo --label claude --dry-run

# Scan all your repos for "aiorchestra"-labeled issues (one-shot)
aiorchestra dispatch

# Dispatch for a specific owner
aiorchestra dispatch --owner myorg
```

`--watch` turns any command into a long-running loop. It polls for new issues, processes them, sleeps for `--poll-interval` seconds (default 300), and repeats. SIGINT/SIGTERM finishes the current cycle before exiting — no orphaned child processes or stuck labels.

Branches are created as `<agent>/<issue-number>`, for example `claude/42` or `codex/42`.
Issues must include the normalized agent-family label derived from `ai.provider`. Assignment to an agent is optional metadata.

### Multi-repo dispatch

The `dispatch` command scans all repos owned by a GitHub user (or org) for issues labeled `aiorchestra`, groups them by repo, resolves the agent family from each issue's labels, and fans out to per-repo Pipeline instances.

## OSINT enrichment

The optional OSINT stage runs **before** implementation to gather external intelligence about targets (domains, IPs) mentioned in the issue. It runs entirely locally — zero cloud AI tokens spent.

**How it works:**

1. **Extract targets** — domains and IPs are auto-extracted from the issue title/body (or configured explicitly)
2. **Run collectors** — shell tools (whois, dig, curl, nmap, etc.) gather raw data about each target
3. **Summarise locally** — raw output is distilled into a structured brief via a local Ollama model
4. **Inject into prompt** — the summary is added to the implementation prompt as OSINT context

**Requirements:**

- OSINT tools on PATH (whois, dig, host, curl — most are pre-installed on Linux)
- [Ollama](https://ollama.com/) running locally for summarisation (optional — falls back to raw output)
- Any small model that fits your GPU: `mistral`, `llama3`, `phi3`, etc.

**Quick start:**

```yaml
# in aiorchestra.yaml
osint:
  enabled: true
  ollama:
    model: "mistral"   # or whatever fits your GPU
```

Targets are auto-extracted from issue text. To override:

```yaml
osint:
  enabled: true
  targets: ["target.io", "192.168.1.1"]
```

Available collectors: `whois`, `dig`, `dig-mx`, `dig-ns`, `dig-txt`, `host`, `http-headers`, `nmap-quick`. Only tools found on PATH are executed; missing tools are silently skipped.

## Configuration

Create `aiorchestra.yaml` in the target repo (or pass `--config`):

```yaml
label: "claude"

ai:
  provider: "claude-code"   # "claude-code" (CLI) or "claude-api"
  model: "claude-opus-4-6"
  max_retries: 3
  skip_permissions: true    # use --dangerously-skip-permissions (default: true)
  # allowed_tools:          # optional — restrict agent's tool access
  #   - Read
  #   - Write
  #   - Edit
  #   - Bash
  #   - Glob
  #   - Grep
  # token_budget: 100000    # optional cap per issue

test:
  command: "pytest"
  lint_command: "ruff check ."

review:
  enabled: true
  provider: "claude-code"   # can differ from implementation provider

ci:
  enabled: true
  timeout: 600              # seconds to wait for CI
  poll_interval: 30

osint:
  enabled: false           # flip to true to activate
  collectors: ["whois", "dig", "dig-mx", "dig-ns", "dig-txt", "host", "http-headers"]
  targets: []              # auto-extracted from issue text when empty
  ollama:
    enabled: true
    endpoint: "http://localhost:11434"
    model: "mistral"       # any model that fits your GPU
    timeout: 120
```

### Watch mode

```yaml
watch:
  poll_interval: 300    # seconds between scans (default: 5 minutes)
```

CLI `--poll-interval` overrides this value.

### Agent routing

The active AI provider determines the required agent-family label. Provider
IDs are normalized into families by `normalize_agent_family()` in
`aiorchestra/ai/_agents.py`:

| Provider id | Family | Required issue label | Invocation mode |
|-------------|--------|----------------------|-----------------|
| `claude-code` | `claude` | `claude` | Local `claude` CLI (`--print`) |
| `codex` | `codex` | `codex` | Local `codex exec --full-auto` |
| `gemini` | `gemini` | `gemini` | Local `gemini -p --yolo` |
| `opencode` | `opencode` | `opencode` | Local `opencode run --yes` |
| `jules` | `jules` | `jules` | Remote async session via `jules remote new` |
| `ollama` | *(not a dispatch target)* | — | Local HTTP; used for OSINT summarisation and as a cross-model reviewer |

`resolve_agent()` scans issue labels for a known agent name (first match
wins). If no label matches, the configured default from `ai.provider` is
used. `KNOWN_AGENTS` is the source of truth: `("claude", "codex", "gemini",
"jules", "opencode")`.

Ollama isn't a dispatch target because it can't edit files on its own — it's
a text-in/text-out LLM. It's wired in as a local summariser for the OSINT
stage and is available as a T4 cross-model reviewer.

## Target repo integration

Target repos can override config and templates by adding a `.aiorchestra/` directory:

```
your-project/
├── .aiorchestra/
│   ├── config.yaml        # Override test commands, retry limits, etc.
│   └── templates/         # Override any prompt template
│       └── implement.md   # Custom implementation prompt
├── CLAUDE.md              # Agent instructions (read by Claude Code)
└── ...
```

**Resolution order** (first found wins for templates, layered merge for config):

| Layer | Templates | Config |
|-------|-----------|--------|
| 1. Target repo | `.aiorchestra/templates/*.md` | `.aiorchestra/config.yaml` |
| 2. AIOrchestra defaults | `aiorchestra/templates/*.md` | Built-in `DEFAULTS` |

**Built-in templates:** `implement`, `fix_validation`, `fix_ci`, `review`,
`review_cross_model`, `fix_review`, `rework`, `osint_summarize` — each uses
`{variable}` placeholders filled by the pipeline.

**Agent instructions** (CLAUDE.md, AGENTS.md, etc.) belong in the target repo, not AIOrchestra. They describe that codebase's conventions and are read directly by the AI agent.

## Project structure

```
aiorchestra/
├── __init__.py
├── _logging.py           # Colored terminal log formatter
├── _sentry.py            # Optional Sentry error reporting
├── cli.py                # CLI entry point (run, dispatch, --watch loop)
├── config.py             # Config loader (3-layer merge: defaults → repo → explicit)
├── dispatcher.py         # Multi-repo issue discovery & fan-out
├── pipeline.py           # Stage runner / state machine (fork-per-issue)
├── ai/                   # Strategy pattern — one file per provider
│   ├── __init__.py       # Public API: AIProvider, InvokeResult, create_provider, …
│   ├── _agents.py        # Agent family normalization & routing (KNOWN_AGENTS)
│   ├── _base.py          # AIProvider ABC + InvokeResult + NEEDS_CLARIFICATION parsing
│   ├── _cli.py           # CLIProvider intermediate base for CLI-backed providers
│   ├── _registry.py      # create_provider() factory
│   ├── _claude_code.py   # Claude Code CLI (local, `claude --print`)
│   ├── _codex.py         # OpenAI Codex CLI (local, `codex exec`)
│   ├── _gemini.py        # Google Gemini CLI (local, `gemini -p`)
│   ├── _jules.py         # Google Jules (remote async session)
│   ├── _ollama.py        # Ollama local LLM (HTTP) — used by OSINT & cross-review
│   └── _opencode.py      # OpenCode CLI (local, `opencode run`)
├── stages/               # One module per pipeline stage; contracts in types.py
│   ├── __init__.py
│   ├── _shell.py         # ALL subprocess calls funnel through run_command()
│   ├── types.py          # IssueData, FeedbackResult, PublishResult, Protocol classes
│   ├── labels.py         # GitHub label helpers + lifecycle constants
│   ├── discover.py       # Find labeled issues (single-repo or multi-repo)
│   ├── prepare.py        # Clone/fetch + checkout + venv + deps
│   ├── osint.py          # OSINT enrichment (shell tools + Ollama summariser)
│   ├── clarification.py  # Defer ambiguous issues with a question comment
│   ├── implement.py      # Invokes the AI provider with the rendered prompt
│   ├── validate.py       # T0 lint + tests, T1 static analysis
│   ├── publish.py        # Commit + push + `gh pr create` (or update)
│   ├── ci.py             # Poll `gh pr checks` until completion
│   └── review.py         # T3 ai-review, T4 cross-model-review, T5 human-required
└── templates/            # Prompt templates, overridable from target repo
    ├── __init__.py       # Template loader with override resolution
    ├── implement.md      # Default implementation prompt (clarification protocol baked in)
    ├── fix_validation.md # Retry prompt after a Validate failure
    ├── fix_ci.md         # Retry prompt after a CI failure
    ├── review.md         # Primary AI review (T3)
    ├── review_cross_model.md # Cross-model review (T4)
    ├── fix_review.md     # Retry prompt after a Review failure
    ├── rework.md         # Rework prompt for human-requested changes
    └── osint_summarize.md # Local summarisation prompt for Ollama
```

## Running as a service

`--watch` keeps AIOrchestra running in the foreground. For a proper background service, use systemd, tmux, or cron.

**systemd** (recommended for headless machines):

```ini
# ~/.config/systemd/user/aiorchestra.service
[Unit]
Description=AIOrchestra watch daemon
After=network-online.target

[Service]
ExecStart=%h/.local/bin/aiorchestra dispatch --watch
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now aiorchestra
journalctl --user -u aiorchestra -f   # tail logs
```

**tmux / screen** (quick and simple):

```bash
tmux new -d -s aiorchestra 'aiorchestra dispatch --watch'
```

**cron** (if you prefer one-shot runs):

```bash
*/5 * * * * aiorchestra dispatch 2>&1 | logger -t aiorchestra
```

## Design principles

- **Always-on by design**: Start it, walk away — `--watch` continuously polls for new issues
- **Deterministic by default**: Only invoke AI when the task genuinely requires reasoning
- **Token-conscious**: Every shell command that replaces an AI call saves tokens
- **Retry with context**: Failures feed error output back to the AI — it learns from each attempt
- **Parallel by default**: Each issue is forked into its own process for concurrent execution
- **Simple and hackable**: Plain Python, no frameworks, easy to modify

## License

MIT
