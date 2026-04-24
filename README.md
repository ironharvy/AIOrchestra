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

### Agent clarification protocol

When the AI agent encounters an ambiguous or underspecified issue, it can signal this by emitting a `NEEDS_CLARIFICATION:` marker in its output instead of guessing:

```
NEEDS_CLARIFICATION: Should this endpoint return 404 or 204 when the collection is empty?
```

The pipeline detects this, posts the question as a comment on the GitHub issue, adds a `needs-clarification` label, and defers the issue. Future runs skip it until a human removes the label.

### Issue lifecycle labels

The pipeline uses GitHub labels to track issue state and prevent collisions across concurrent runs:

| Label | Meaning | Added | Removed |
|-------|---------|-------|---------|
| `agent-working` | An agent has claimed this issue | Before processing starts | On completion, failure, or deferral |
| `needs-clarification` | Waiting on human input | When agent signals ambiguity | Manually, after the human responds |

Discovery skips issues carrying either label.

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

# Watch a single repo — each issue auto-routes to the agent named in its labels
aiorchestra run --repo owner/repo --watch

# Custom poll interval (seconds)
aiorchestra dispatch --watch --poll-interval 120

# One-shot: process every aiorchestra-labeled issue, routing per-issue
aiorchestra run --repo owner/repo

# One-shot: pin a specific agent family (claude, codex, gemini, jules, opencode)
aiorchestra run --repo owner/repo --label codex

# One-shot: process a specific issue
aiorchestra run --repo owner/repo --issue 42

# Dry run — show what would happen without executing
aiorchestra run --repo owner/repo --dry-run

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

The active AI provider determines the required agent-family label. Provider IDs are normalized into families:

| Provider | Family | Required label |
|----------|--------|----------------|
| `claude-code`, `claude-api` | `claude` | `claude` |
| `codex`, `codex-v2` | `codex` | `codex` |
| `jules` | `jules` | `jules` |
| `opencode` | `opencode` | `opencode` |

`resolve_agent()` scans issue labels for a known agent name — first match wins. If no label matches, the configured default is used.

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

**Built-in templates:** `implement`, `fix_validation`, `fix_ci`, `review`, `fix_review`, `osint_summarize` — each uses `{variable}` placeholders filled by the pipeline.

**Agent instructions** (CLAUDE.md, AGENTS.md, etc.) belong in the target repo, not AIOrchestra. They describe that codebase's conventions and are read directly by the AI agent.

## Project structure

```
aiorchestra/
├── __init__.py
├── cli.py              # CLI entry point (run, dispatch, --watch loop)
├── config.py           # Config loader (3-layer merge)
├── agents.py           # Agent family normalization & routing
├── dispatcher.py       # Multi-repo issue discovery & dispatch
├── pipeline.py         # Stage runner / state machine (fork-per-issue)
├── _logging.py         # Colored terminal log formatter
├── ai/
│   ├── __init__.py
│   ├── claude.py       # Claude Code CLI wrapper, InvokeResult
│   └── ollama.py       # Ollama local LLM provider
├── stages/
│   ├── __init__.py
│   ├── _shell.py       # Shared subprocess helpers
│   ├── types.py        # Shared types & protocols
│   ├── labels.py       # GitHub label management (agent-working, needs-clarification)
│   ├── clarification.py # Defer ambiguous issues with a question comment
│   ├── discover.py     # Find labeled issues (single repo or multi-repo)
│   ├── prepare.py      # Git + env setup
│   ├── osint.py        # OSINT enrichment (shell tools + Ollama)
│   ├── implement.py    # AI implementation invocation
│   ├── validate.py     # Tests + linting
│   ├── publish.py      # Push + PR creation
│   ├── ci.py           # CI status polling
│   └── review.py       # AI code review
└── templates/
    ├── __init__.py     # Template loader with override resolution
    ├── implement.md    # Default implementation prompt (includes clarification protocol)
    ├── osint_summarize.md # OSINT summarisation prompt for local Ollama
    ├── fix_validation.md
    ├── fix_ci.md
    ├── review.md
    └── fix_review.md
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
