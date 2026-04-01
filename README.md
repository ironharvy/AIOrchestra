# AIOrchestra

A lightweight wrapper that orchestrates AI coding agents with deterministic shell automation. Instead of burning tokens on git commands and test runs, AIOrchestra handles the predictable work and only invokes the AI when intelligence is actually needed.

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
# Process all issues labeled "claude" in a repo
aiorchestra run --repo owner/repo --label claude

# Process a specific issue
aiorchestra run --repo owner/repo --issue 42

# Dry run — show what would happen without executing
aiorchestra run --repo owner/repo --label claude --dry-run

# Scan all your repos for "aiorchestra"-labeled issues and dispatch
aiorchestra dispatch

# Dispatch for a specific owner
aiorchestra dispatch --owner myorg
```

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
  model: "sonnet"
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

### Agent routing

The active AI provider determines the required agent-family label. Provider IDs are normalized into families:

| Provider | Family | Required label |
|----------|--------|----------------|
| `claude-code`, `claude-api` | `claude` | `claude` |
| `codex`, `codex-v2` | `codex` | `codex` |
| `jules` | `jules` | `jules` |

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
├── cli.py              # CLI entry point (run, dispatch)
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

## Design principles

- **Deterministic by default**: Only invoke AI when the task genuinely requires reasoning
- **Token-conscious**: Every shell command that replaces an AI call saves tokens
- **Retry with context**: Failures feed error output back to the AI — it learns from each attempt
- **Parallel by default**: Each issue is forked into its own process for concurrent execution
- **Simple and hackable**: Plain Python, no frameworks, easy to modify

## License

MIT
