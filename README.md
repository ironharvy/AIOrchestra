# AIOrchestra

A lightweight wrapper that orchestrates AI coding agent with deterministic shell automation. Instead of burning tokens on git commands and test runs, AIOrchestra handles the predictable work and only invokes the AI when intelligence is actually needed.

## How it works

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Discover    │────▶│  Prepare    │────▶│  OSINT       │────▶│  Implement   │
│  (gh/shell)  │     │  (git/sh)   │     │  (shell/LLM) │     │  (AI agent)  │
└─────────────┘     └─────────────┘     └──────────────┘     └──────┬───────┘
                                                                    │
                    ┌──────────────┐                         ┌──────▼──────┐
                    │  Validate    │◀────────────────────────│             │
                    │  (sh/tests)  │        on failure ──────│  Implement  │
                    └──────┬───────┘                         └─────────────┘
                           │
                    ┌──────▼──────┐     ┌─────────────┐     ┌─────────────┐
                    │  Publish    │────▶│  CI Watch   │────▶│  Review     │
                    │  (git/gh)   │     │  (gh/poll)  │     │  (AI agent) │
                    └─────────────┘     └──────┬──────┘     └──────┬──────┘
                                               │                   │
                                               └─── on failure ────┘──▶ re-invoke AI with context
```

### Pipeline stages

| Stage | What runs | AI? | Description |
|-------|-----------|-----|-------------|
| **Discover** | `gh issue list --label <label>` | No | Find issues tagged for automation |
| **Prepare** | git pull, checkout -b, venv setup | No | Set up a clean working environment |
| **OSINT** | whois, dig, curl + Ollama | Local | Gather external intelligence about targets in the issue |
| **Implement** | Claude Code / API | Yes | Generate implementation from issue description + OSINT context |
| **Validate** | pytest, ruff/flake8, mypy | No | Run tests and linters locally |
| **Publish** | git push, gh pr create | No | Create PR and push changes |
| **CI Watch** | Poll `gh run list` | No | Wait for CI to pass |
| **Review** | Claude Code / API | Yes | AI code review on the diff |

On failure at Validate, CI, or Review — the AI is re-invoked with the error output appended to the prompt. A configurable retry cap prevents infinite loops.

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
```

Branches are created as `<agent>/<issue-number>`, for example `claude/42` or `codex/42`.
Issues must include the normalized agent-family label derived from `ai.provider`. Assignment to an agent is optional metadata.

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
  provider: "claude-code"  # "claude-code" (CLI) or "claude-api"
  model: "sonnet"          # for API mode
  max_retries: 3
  # token_budget: 100000   # optional cap per issue

test:
  command: "pytest"
  lint_command: "ruff check ."

review:
  enabled: true
  provider: "claude-code"  # can differ from implementation provider

ci:
  enabled: true
  timeout: 600             # seconds to wait for CI
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

**Issue routing:** the active implementation provider determines the required agent-family label on issues. For example, `claude-code` and `claude-api` both require a `claude` label, while a future Codex provider would require `codex`. The optional `label` config or `--label` flag can still be used as an additional GitHub filter.

## Project structure

```
aiorchestra/
├── __init__.py
├── cli.py            # CLI entry point
├── config.py         # Config loader (3-layer merge)
├── pipeline.py       # Stage runner / state machine
├── templates/
│   ├── __init__.py   # Template loader with override resolution
│   ├── implement.md  # Default implementation prompt
│   ├── fix_validation.md
│   ├── fix_ci.md
│   ├── review.md
│   └── fix_review.md
├── stages/
│   ├── __init__.py
│   ├── discover.py   # Find labeled issues
│   ├── prepare.py    # Git + env setup
│   ├── osint.py      # OSINT enrichment (shell tools + Ollama)
│   ├── implement.py  # AI implementation
│   ├── validate.py   # Tests + linting
│   ├── publish.py    # Push + PR creation
│   ├── ci.py         # CI status polling
│   └── review.py     # AI code review
└── ai/
    ├── __init__.py
    ├── claude.py     # Claude Code CLI wrapper
    └── ollama.py     # Ollama local LLM provider
```

## Design principles

- **Deterministic by default**: Only invoke AI when the task genuinely requires reasoning
- **Token-conscious**: Every shell command that replaces an AI call saves tokens
- **Retry with context**: Failures feed error output back to the AI — it learns from each attempt
- **Simple and hackable**: Plain Python, no frameworks, easy to modify

## License

MIT
