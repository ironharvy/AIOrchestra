"""Pipeline — the state machine that drives each issue through stages."""

import logging

from aiorchestra.stages.discover import discover_issues
from aiorchestra.stages.prepare import prepare_environment
from aiorchestra.stages.implement import implement
from aiorchestra.stages.validate import validate
from aiorchestra.stages.publish import publish
from aiorchestra.stages.ci import wait_for_ci
from aiorchestra.stages.review import review
from aiorchestra.templates import render_template

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        repo: str,
        label: str,
        config: dict,
        issue_number: int | None = None,
        dry_run: bool = False,
        repo_root: str | None = None,
    ):
        self.repo = repo
        self.label = label
        self.issue_number = issue_number
        self.config = config
        self.dry_run = dry_run
        self.repo_root = repo_root
        self.max_retries = config.get("ai", {}).get("max_retries", 3)

    def run(self) -> int:
        """Run the full pipeline. Returns 0 on success, 1 on failure."""
        issues = discover_issues(self.repo, self.label, self.issue_number)
        if not issues:
            log.info("No issues found.")
            return 0

        for issue in issues:
            log.info("Processing issue #%d: %s", issue["number"], issue["title"])
            if self.dry_run:
                log.info("[dry-run] Would process issue #%d", issue["number"])
                continue

            ok = self._process_issue(issue)
            if not ok:
                log.error("Failed to process issue #%d", issue["number"])
                return 1

        return 0

    def _process_issue(self, issue: dict) -> bool:
        branch = f"{self.config.get('branch_prefix', 'auto/')}{issue['number']}"

        # Stage 1: Prepare environment (deterministic)
        if not prepare_environment(self.repo, branch):
            return False

        # Stage 2: Implement (AI) + Validate (deterministic), with retries
        for attempt in range(1, self.max_retries + 1):
            log.info("Implementation attempt %d/%d", attempt, self.max_retries)

            errors = None if attempt == 1 else validation_errors
            if not implement(issue, self.config, previous_errors=errors,
                             repo_root=self.repo_root):
                return False

            ok, validation_errors = validate(self.config)
            if ok:
                break
        else:
            log.error("Validation failed after %d attempts", self.max_retries)
            return False

        # Stage 3: Publish (deterministic)
        pr_url = publish(self.repo, branch, issue)
        if not pr_url:
            return False

        # Stage 4: CI (deterministic polling) + fix loop
        if self.config.get("ci", {}).get("enabled", True):
            for attempt in range(1, self.max_retries + 1):
                ok, ci_output = wait_for_ci(pr_url, self.config)
                if ok:
                    break
                log.info("CI failed, attempt %d/%d", attempt, self.max_retries)

                ci_prompt_errors = render_template(
                    "fix_ci",
                    repo_root=self.repo_root,
                    number=issue["number"],
                    title=issue["title"],
                    body=issue.get("body", ""),
                    errors=ci_output,
                )
                if not implement(issue, self.config, previous_errors=ci_prompt_errors,
                                 repo_root=self.repo_root):
                    return False
            else:
                log.error("CI failed after %d attempts", self.max_retries)
                return False

        # Stage 5: Review (AI) + fix loop
        if self.config.get("review", {}).get("enabled", True):
            for attempt in range(1, self.max_retries + 1):
                ok, feedback = review(self.repo, branch, self.config, issue=issue,
                                      repo_root=self.repo_root)
                if ok:
                    break
                log.info("Review flagged issues, attempt %d/%d", attempt, self.max_retries)

                review_errors = render_template(
                    "fix_review",
                    repo_root=self.repo_root,
                    number=issue["number"],
                    title=issue["title"],
                    body=issue.get("body", ""),
                    errors=feedback,
                )
                if not implement(issue, self.config, previous_errors=review_errors,
                                 repo_root=self.repo_root):
                    return False
            else:
                log.error("Review failed after %d attempts", self.max_retries)
                return False

        log.info("Issue #%d completed successfully.", issue["number"])
        return True
