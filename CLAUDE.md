# AIOrchestra - Agent Instructions

AI agent orchestration framework. Pipelines process GitHub issues through
discover → implement → validate → review → publish stages.

## Architecture

- **Stages** (`aiorchestra/stages/`): Each stage is a module with a main entry
  function returning a typed result from `stages/types.py`.
- **AI providers** (`aiorchestra/ai/`): All providers inherit `AIProvider` ABC
  and implement `run()`. Use `create_provider()` factory, never instantiate directly.
- **Shell** (`stages/_shell.py`): All subprocess calls go through `run_command()`.
  Never call `subprocess.run()` directly outside this module.
- **Config** (`config.py`): Three-layer merge (defaults → repo config → explicit).
  Always use `_deep_merge()`, never plain `dict.update()`.
- **Templates** (`aiorchestra/templates/`): Prompt templates rendered via
  `render_template()`. One file per stage/purpose.

## Adding new stages

1. Create `aiorchestra/stages/your_stage.py`
2. Define entry function with typed return from `stages/types.py`
3. Add tests in `tests/test_your_stage.py`
4. Wire into pipeline in `pipeline.py`

## Adding new AI providers

1. Create class inheriting `AIProvider` in `aiorchestra/ai/`
2. Implement `run()` with exact signature from ABC
3. Register in `create_provider()` factory
4. Add `available()` check if provider needs external service

## Conventions

- Check `shutil.which()` before invoking external CLI tools
- Return failure results, don't raise exceptions in stages
- Use `config.get(key, default)` not `config[key]` for optional values
- Tests required for all stages and providers
- No new runtime dependencies without an ADR in think_tank

## Quality

Enforced by CI, not by this file:
- Ruff (style, line-length=100)
- Bandit (security)
- Semgrep (custom rules in `.semgrep/`)
- pytest (all tests must pass)
