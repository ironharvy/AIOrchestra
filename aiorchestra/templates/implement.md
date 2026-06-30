Work on the following GitHub issue.

Issue #{number}: {title}

{body}
{osint_context}{comments_section}
Read the issue body carefully and act accordingly. The issue may describe
a coding task, a documentation task, or a planning task depending on the
role it assigns you. Whatever the role, you must leave at least one
committed change in the worktree — the orchestrator needs a diff to open
a pull request. If the role is non-coding (CEO, BA, PM, Tech Lead,
Researcher, QA, DevOps), commit your deliverable as a markdown file
under `docs/` unless the issue says otherwise. If the role is coding,
implement the changes directly.

Do not run tests as part of this step — a later pipeline stage handles
validation.

## Clarification protocol

If the issue description is ambiguous, contradictory, or missing critical
information that prevents you from producing a correct deliverable, do NOT
guess. Instead, output a single line starting with the marker below, followed
by a concise question for the issue author:

    NEEDS_CLARIFICATION: <your question here>

When you output this marker you must NOT make any file changes — the
orchestrator will post your question as a comment on the issue and pause
work until the author responds.

Only use this when the ambiguity would lead to a materially wrong
deliverable. Minor stylistic uncertainties should be resolved using your
best judgement.
