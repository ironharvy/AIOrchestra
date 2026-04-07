Review the following code diff for issue #{number}: {title}

Focus on:
- Bugs or logic errors
- Security issues
- Missing edge cases
- **Shortcut anti-patterns** — flag if the diff:
  - Wraps imports in try/except ImportError (should add dependency instead)
  - Changes linter/formatter config (line-length, disabled rules, etc.)
  - Adds blanket `# noqa` or `# type: ignore` comments
  - Modifies CI workflows or test thresholds to make checks pass
  - Weakens or deletes existing tests instead of fixing code

If the code looks good, respond with exactly: LGTM
If there are issues, describe them clearly.

```diff
{diff}
```
