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

## Bug Fix Rules

When a CI check, linter, or test fails, fix the code — never weaken the tool:

1. **Never weaken or disable a linter/formatter rule to fix a violation.**
   Fix the code to comply with the existing rule. Do not change line-length,
   disable rules, add `noqa` comments, or alter tool configs.
2. **Never wrap imports in try/except to hide missing dependencies.**
   Add the dependency to `pyproject.toml` `[project.dependencies]` (or
   `[project.optional-dependencies]`) and, if present, `requirements.txt`.
3. **Never modify CI workflows, test thresholds, semgrep rules, or tool
   configs to make a failing check pass** unless explicitly asked by a human.
4. **Prefer the smallest, most targeted fix.** If a one-line change fixes it,
   don't restructure surrounding code.
5. **Diagnose before fixing.** When a check fails, first identify *what rule*
   was violated and *why*, then choose a fix that addresses the root cause.
   A fix is correct when it satisfies the rule's intent, not just when CI
   turns green.
6. **Protected files — changes require human approval:**
   `pyproject.toml [tool.*]`, `.semgrep/`, `.github/workflows/`,
   `.ruff.toml`, `setup.cfg`. If a fix seems to require changing these,
   stop and ask.

## Quality

Enforced by CI, not by this file:
- Ruff (style, line-length=100)
- Bandit (security)
- Semgrep (custom rules in `.semgrep/`)
- pytest (all tests must pass)
