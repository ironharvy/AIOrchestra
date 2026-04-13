Code review flagged issues with your implementation of issue #{number}.

Issue #{number}: {title}

{body}

Review feedback:

{errors}

## Instructions

Follow these steps IN ORDER:

### Step 1 — Understand the feedback
For each review comment, determine:
- What specific concern was raised
- Whether it's about correctness, security, style, or design
- What file and code section it refers to

### Step 2 — Plan the fix
For each concern:
- If it's a bug or security issue: fix the code
- If it's a style concern: follow the project's existing conventions
- If it's a design concern: make the minimum change that addresses it
- NEVER weaken linters, suppress warnings, or modify configs to resolve feedback

### Step 3 — Apply
Address each review point with the smallest correct change.
Do NOT restructure surrounding code or add unrelated improvements.

Do NOT run tests — just fix the code.
