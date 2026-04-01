"""Clarification stage — defer an issue when the agent needs human input.

Posts a comment on the GitHub issue with the agent's question and adds a
``needs-clarification`` label so the discover stage skips it on future runs.
"""

from __future__ import annotations

import logging

from aiorchestra.stages._shell import run_command
from aiorchestra.stages.types import IssueData

log = logging.getLogger(__name__)

CLARIFICATION_LABEL = "needs-clarification"


def request_clarification(
    repo: str,
    issue: IssueData,
    message: str,
) -> bool:
    """Post a clarification comment and label the issue.

    Returns True if both the comment and the label were applied successfully.
    """
    number = issue["number"]
    body = (
        f"🤖 **Automated clarification request**\n\n"
        f"While working on this issue the AI agent encountered ambiguity "
        f"and needs human input before it can proceed:\n\n"
        f"> {message}\n\n"
        f"Once you've responded, remove the `{CLARIFICATION_LABEL}` label "
        f"to allow the agent to retry."
    )

    comment_ok = _add_comment(repo, number, body)
    label_ok = _add_label(repo, number)

    if comment_ok and label_ok:
        log.info(
            "Issue #%d deferred — clarification requested", number,
        )
    return comment_ok and label_ok


def _add_comment(repo: str, number: int, body: str) -> bool:
    result = run_command(
        ["gh", "issue", "comment", str(number), "--repo", repo, "--body", body],
        logger=log,
    )
    if result.returncode != 0:
        log.error("Failed to comment on issue #%d: %s", number, result.stderr.strip())
        return False
    return True


def _add_label(repo: str, number: int) -> bool:
    result = run_command(
        ["gh", "issue", "edit", str(number), "--repo", repo,
         "--add-label", CLARIFICATION_LABEL],
        logger=log,
    )
    if result.returncode != 0:
        log.error(
            "Failed to add label '%s' to issue #%d: %s",
            CLARIFICATION_LABEL, number, result.stderr.strip(),
        )
        return False
    return True
