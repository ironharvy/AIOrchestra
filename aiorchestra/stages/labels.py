"""GitHub issue label management via the ``gh`` CLI.

Centralises label operations so that the pipeline, clarification stage, and
any future stages that need to manipulate issue labels share a single
implementation.
"""

from __future__ import annotations

import logging

from aiorchestra.stages._shell import run_command

log = logging.getLogger(__name__)

# Labels used as lifecycle state markers.
LABEL_WORKING = "agent-working"
LABEL_NEEDS_CLARIFICATION = "needs-clarification"

# Issues carrying any of these labels are skipped during discovery.
SKIP_LABELS: frozenset[str] = frozenset({LABEL_WORKING, LABEL_NEEDS_CLARIFICATION})


def add_label(repo: str, issue_number: int, label: str) -> bool:
    """Add *label* to issue *issue_number*. Returns True on success."""
    result = run_command(
        ["gh", "issue", "edit", str(issue_number), "--repo", repo, "--add-label", label],
        logger=log,
    )
    if result.returncode != 0:
        log.error(
            "Failed to add label '%s' to #%d: %s",
            label,
            issue_number,
            result.stderr.strip(),
        )
        return False
    log.debug("Added label '%s' to #%d", label, issue_number)
    return True


def remove_label(repo: str, issue_number: int, label: str) -> bool:
    """Remove *label* from issue *issue_number*. Returns True on success."""
    result = run_command(
        ["gh", "issue", "edit", str(issue_number), "--repo", repo, "--remove-label", label],
        logger=log,
    )
    if result.returncode != 0:
        log.error(
            "Failed to remove label '%s' from #%d: %s",
            label,
            issue_number,
            result.stderr.strip(),
        )
        return False
    log.debug("Removed label '%s' from #%d", label, issue_number)
    return True
