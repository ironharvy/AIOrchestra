CI failed for issue #{number}.

Issue #{number}: {title}

{body}

CI output:

{errors}

## Instructions

Follow these steps IN ORDER:

### Step 1 — Diagnose
Read the CI output carefully. For each failure, identify:
- Which CI job failed (lint, test, security scan, etc.)
- What specific rule or assertion was violated
- What file and line caused it

### Step 2 — Plan the fix
For each failure, choose the CORRECT fix:
- **Lint/format violation**: change the code to comply with the rule.
  NEVER change linter config, disable rules, or add noqa comments.
- **Missing dependency**: add it to pyproject.toml and/or requirements.txt.
  NEVER wrap imports in try/except.
- **Test failure**: fix the logic bug in the implementation.
  NEVER weaken the test assertion or delete the test.
- **Security finding**: fix the insecure pattern in the code.
  NEVER disable the security rule.

### Step 3 — Apply
Make the smallest, most targeted fix for each error. Do NOT restructure
surrounding code, add unrelated improvements, or modify CI config files.

Do NOT run tests — just fix the code.
