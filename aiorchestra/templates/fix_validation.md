Your previous implementation for issue #{number} failed validation.

Issue #{number}: {title}

{body}

The following errors occurred:

{errors}

## Instructions

Follow these steps IN ORDER:

### Step 1 — Diagnose
Identify what EACH error means. For each error, determine:
- What rule or check was violated (e.g. ruff E501, missing import, test assertion)
- What the root cause is in your code

### Step 2 — Plan the fix
For each error, choose the CORRECT fix:
- **Lint/format violation**: change the code to comply with the rule.
  NEVER change linter config, disable rules, or add noqa comments.
- **Missing dependency**: add it to pyproject.toml and/or requirements.txt.
  NEVER wrap imports in try/except.
- **Test failure**: fix the logic bug in the implementation.
  NEVER weaken the test assertion or delete the test.
- **Type error**: fix the type mismatch in the code.
  NEVER add blanket `# type: ignore`.

### Step 3 — Apply
Make the smallest, most targeted fix for each error. Do NOT restructure
surrounding code, add unrelated improvements, or modify config files.

Do NOT run tests — just fix the code.
