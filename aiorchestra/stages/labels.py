"""GitHub issue label management via the ``gh`` CLI.

Centralises label operations so that the pipeline, clarification stage, and
any future stages that need to manipulate issue labels share a single
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging

from aiorchestra.stages._shell import run_command

log = logging.getLogger(__name__)

# Labels used as lifecycle state markers.
LABEL_WORKING = "agent-working"
LABEL_NEEDS_CLARIFICATION = "needs-clarification"
LABEL_AWAITING_REVIEW = "awaiting-review"
LABEL_FAILED = "agent-failed"

# Issues carrying any of these labels are skipped during discovery.
SKIP_LABELS: frozenset[str] = frozenset(
    {
        LABEL_WORKING,
        LABEL_NEEDS_CLARIFICATION,
        LABEL_AWAITING_REVIEW,
        LABEL_FAILED,
    }
)


@dataclass(frozen=True)
class LabelDef:
    """A label definition with name, color, and description."""

    name: str
    color: str  # hex color without leading '#'
    description: str


# All labels that AIOrchestra may create or interact with.
MANAGED_LABELS: tuple[LabelDef, ...] = (
    LabelDef("agent-working", "fbca04", "AIOrchestra: issue is being processed by an agent"),
    LabelDef("needs-clarification", "d93f0b", "AIOrchestra: waiting for human clarification"),
    LabelDef("awaiting-review", "1d76db", "AIOrchestra: PR created, awaiting human review"),
    LabelDef("agent-failed", "e11d48", "AIOrchestra: agent failed, needs human investigation"),
    LabelDef("aiorchestra", "0e8a16", "AIOrchestra: dispatch-eligible issue"),
    LabelDef("claude", "7057ff", "AIOrchestra: process with Claude agent"),
    LabelDef("codex", "1d76db", "AIOrchestra: process with Codex agent"),
    LabelDef("gemini", "006b75", "AIOrchestra: process with Gemini agent"),
    LabelDef("jules", "b60205", "AIOrchestra: process with Jules agent"),
    LabelDef("security", "e11d48", "Requires human review (security-sensitive)"),
    LabelDef("breaking-change", "d93f0b", "Requires human review (breaking change)"),
)


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


def swap_label(repo: str, issue_number: int, remove: str, add: str) -> bool:
    """Remove one label and add another. Returns True only if the add succeeded."""
    remove_label(repo, issue_number, remove)  # best-effort; missing label is fine
    return add_label(repo, issue_number, add)


def _label_exists(repo: str, label_name: str, existing: set[str] | None = None) -> bool:
    """Check if a label already exists in the repo."""
    if existing is not None:
        return label_name.lower() in existing
    result = run_command(
        ["gh", "label", "list", "--repo", repo, "--search", label_name, "--json", "name"],
        logger=log,
    )
    if result.returncode != 0:
        return False
    for item in json.loads(result.stdout or "[]"):
        if item.get("name", "").lower() == label_name.lower():
            return True
    return False


def _fetch_existing_labels(repo: str) -> set[str]:
    """Fetch all existing label names for a repo (lowercased)."""
    result = run_command(
        ["gh", "label", "list", "--repo", repo, "--json", "name", "--limit", "200"],
        logger=log,
    )
    if result.returncode != 0:
        return set()
    return {item["name"].lower() for item in json.loads(result.stdout or "[]")}


def ensure_labels(
    repo: str,
    labels: tuple[LabelDef, ...] | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Create any missing labels in *repo*. Returns names of labels created.

    Existing labels are left untouched (color/description are not overwritten).
    """
    if labels is None:
        labels = MANAGED_LABELS

    existing = _fetch_existing_labels(repo)
    created: list[str] = []

    for label in labels:
        if label.name.lower() in existing:
            log.debug("Label '%s' already exists in %s", label.name, repo)
            continue

        if dry_run:
            log.info("[dry-run] Would create label '%s' in %s", label.name, repo)
            created.append(label.name)
            continue

        result = run_command(
            [
                "gh",
                "label",
                "create",
                label.name,
                "--repo",
                repo,
                "--color",
                label.color,
                "--description",
                label.description,
            ],
            logger=log,
        )
        if result.returncode == 0:
            log.info("Created label '%s' in %s", label.name, repo)
            created.append(label.name)
        else:
            # Label may have been created concurrently — not fatal.
            log.warning(
                "Failed to create label '%s' in %s: %s",
                label.name,
                repo,
                result.stderr.strip(),
            )

    return created
