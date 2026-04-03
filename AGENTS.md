# AIOrchestra - Agent Instructions

AI agent orchestration framework. Pipelines process GitHub issues through
discover → implement → validate → review → publish stages.

## Architecture

- **Stages** (`aiorchestra/stages/`): Each stage is a module with a main entry
  function returning a typed result from `stages/types.py`.
- **AI providers** (`aiorchestra/ai/`): Strategy pattern. `AIProvider` ABC in
  `_base.py`, `CLIProvider` intermediate base in `_cli.py` for CLI-based
  providers, concrete strategies in individual `_*.py` files. Factory in
  `_registry.py`. All public API via `from aiorchestra.ai import ...`.
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

1. Create `aiorchestra/ai/_your_provider.py`
2. For CLI-based providers: inherit `CLIProvider` from `_cli.py`
3. For non-CLI providers: inherit `AIProvider` from `_base.py`
4. Implement `run(prompt, *, system=None, cwd=None) -> InvokeResult`
5. Register in `_registry.py` factory
6. Export in `__init__.py`
7. Add `available()` check if provider needs external service
8. Add tests in `tests/test_your_provider.py`

## Conventions

- Import from package: `from aiorchestra.ai import AIProvider, create_provider`
- Check `shutil.which()` before invoking external CLI tools
- Return failure results, don't raise exceptions in stages
- Use `config.get(key, default)` not `config[key]` for optional values
- Tests required for all stages and providers
- No new runtime dependencies without an ADR in think_tank
- Semgrep custom rules in `.semgrep/` enforce codebase patterns via CI

## Quality

Enforced by CI, not by this file:
- Ruff (style, line-length=100)
- Bandit (security)
- Semgrep (custom rules in `.semgrep/`)
- pytest (all tests must pass)
