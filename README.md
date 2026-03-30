# AIOrchestra

A lightweight wrapper that orchestrates AI coding agents with deterministic shell automation. Instead of burning tokens on git commands and test runs, AIOrchestra handles the predictable work and only invokes the AI when intelligence is actually needed.

## How it works

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Discover    │────▶│  Prepare    │────▶│  Implement   │────▶│  Validate   │
│  (gh/shell)  │     │  (git/sh)   │     │  (AI agent)  │     │  (sh/tests) │
└─────────────┘     └─────────────┘     └──────────────┘     └──────┬──────┘
                                              ▲                     │
                                              └──── on failure ─────┘
                                                                    │
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
| **Discover** | `gh issue list --label <label>` | No | Find issues tagged for automation |
| **Prepare** | git pull, checkout -b, venv setup | No | Set up a clean working environment |
| **Implement** | Claude Code / API | Yes | Generate implementation from issue description |
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

## Configuration

Create `aiorchestra.yaml` in the target repo (or pass `--config`):

```yaml
label: "claude"
branch_prefix: "auto/"

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

**Built-in templates:** `implement`, `fix_validation`, `fix_ci`, `review`, `fix_review` — each uses `{variable}` placeholders filled by the pipeline.

**Agent instructions** (CLAUDE.md, AGENTS.md, etc.) belong in the target repo, not AIOrchestra. They describe that codebase's conventions and are read directly by the AI agent.

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
│   ├── implement.py  # AI implementation
│   ├── validate.py   # Tests + linting
│   ├── publish.py    # Push + PR creation
│   ├── ci.py         # CI status polling
│   └── review.py     # AI code review
└── ai/
    ├── __init__.py
    └── claude.py     # Claude Code CLI wrapper
```

## Design principles

- **Deterministic by default**: Only invoke AI when the task genuinely requires reasoning
- **Token-conscious**: Every shell command that replaces an AI call saves tokens
- **Retry with context**: Failures feed error output back to the AI — it learns from each attempt
- **Simple and hackable**: Plain Python, no frameworks, easy to modify

## License

MIT
