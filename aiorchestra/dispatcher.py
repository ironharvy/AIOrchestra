"""Multi-repo dispatcher — scan all owned repos for actionable issues."""

import logging

from aiorchestra.agents import resolve_agent
from aiorchestra.pipeline import Pipeline
from aiorchestra.stages.discover import discover_all_issues
from aiorchestra.stages.types import PipelineConfig

log = logging.getLogger(__name__)


class Dispatcher:
    """Discover issues across repos and fan out to per-repo Pipelines."""

    def __init__(
        self,
        config: PipelineConfig,
        owner: str = "@me",
        config_path: str | None = None,
        dry_run: bool = False,
        workspace: str | None = None,
    ):
        self.owner = owner
        self.config = config
        self.config_path = config_path
        self.dry_run = dry_run
        self.workspace = workspace

    def run(self) -> int:
        """Discover and process issues across all repos. Returns 0 on success."""
        repo_issues = discover_all_issues(owner=self.owner)
        if not repo_issues:
            log.info("No issues found across repos.")
            return 0

        for repo, issues in repo_issues.items():
            log.info("Dispatching %d issue(s) for %s", len(issues), repo)
            for issue in issues:
                agent = resolve_agent(issue.get("labels", []))
                log.info("  #%d -> %s", issue["number"], agent)

            label = resolve_agent(issues[0].get("labels", []))

            pipeline = Pipeline(
                repo=repo,
                label=label,
                config=self.config,
                config_path=self.config_path,
                dry_run=self.dry_run,
                workspace=self.workspace,
            )
            result = pipeline.run(issues=issues)
            if result != 0:
                return result

        return 0
