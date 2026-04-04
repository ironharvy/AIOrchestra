Issue #{number}: {title}

{body}
{osint_context}{comments_section}

## Existing implementation

This issue was previously implemented on this branch. The code already exists
in the working directory. Your task is to **revise the existing code** based
on the discussion above (especially review feedback in the ## Discussion section).

Do NOT re-implement from scratch. Focus on the specific changes requested.
Do NOT run tests — just make the revisions.

## Clarification protocol

If the issue description is ambiguous, contradictory, or missing critical
information that prevents you from implementing a correct solution, do NOT
guess. Instead, output a single line starting with the marker below, followed
by a concise question for the issue author:

    NEEDS_CLARIFICATION: <your question here>

When you output this marker you must NOT make any file changes — the
orchestrator will post your question as a comment on the issue and pause
work until the author responds.

Only use this when the ambiguity would lead to a materially wrong
implementation. Minor stylistic uncertainties should be resolved using your
best judgement.
