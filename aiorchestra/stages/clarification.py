"""Clarification stage — defer an issue when the agent needs human input.

Posts a comment on the GitHub issue with the agent's question and adds a
``needs-clarification`` label so the discover stage skips it on future runs.
"""

from __future__ import annotations

import logging

from aiorchestra.stages._shell import CommandError, run_command_or_fail
from aiorchestra.stages.labels import LABEL_NEEDS_CLARIFICATION, add_label
from aiorchestra.stages.types import IssueData

log = logging.getLogger(__name__)


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
        f"Once you've responded, remove the `{LABEL_NEEDS_CLARIFICATION}` label "
        f"to allow the agent to retry."
    )

    comment_ok = _add_comment(repo, number, body)
    label_ok = add_label(repo, number, LABEL_NEEDS_CLARIFICATION)

    if comment_ok and label_ok:
        log.info(
            "Issue #%d deferred — clarification requested: %s",
            number,
            message,
        )
    return comment_ok and label_ok


def _add_comment(repo: str, number: int, body: str) -> bool:
    try:
        run_command_or_fail(
            ["gh", "issue", "comment", str(number), "--repo", repo, "--body", body],
            error_msg=f"Failed to comment on issue #{number}",
            logger=log,
        )
    except CommandError:
        return False
    return True
