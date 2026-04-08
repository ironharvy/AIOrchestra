"""CLI entry point for AIOrchestra."""

import argparse
import logging
import signal
import sys
import time
from typing import Callable

from aiorchestra._logging import setup_logging
from aiorchestra._sentry import init as _init_sentry
from aiorchestra.config import load_config
from aiorchestra.dispatcher import Dispatcher
from aiorchestra.pipeline import Pipeline
from aiorchestra.stages.labels import ensure_labels

log = logging.getLogger(__name__)


def _watch_loop(fn: Callable[[], int], poll_interval: int) -> int:
    """Call *fn* in a loop, sleeping *poll_interval* seconds between cycles.

    Handles SIGINT/SIGTERM so the current cycle finishes before exit.
    """
    shutdown = False

    def _handle_signal(sig: int, _frame: object) -> None:
        nonlocal shutdown
        log.info("Received signal %d — finishing current cycle then exiting", sig)
        shutdown = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info("Watch mode active — polling every %ds", poll_interval)

    while not shutdown:
        fn()
        if shutdown:
            break
        log.info("Next scan in %ds", poll_interval)
        for _ in range(poll_interval):
            if shutdown:
                break
            time.sleep(1)

    log.info("Watch mode stopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiorchestra",
        description="Orchestrate AI coding agents with deterministic shell automation.",
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Process issues and drive the AI pipeline")
    run.add_argument("--repo", required=True, help="GitHub repo (owner/repo)")
    run.add_argument("--label", default=None, help="Issue label to filter by")
    run.add_argument("--issue", type=int, default=None, help="Specific issue number")
    run.add_argument("--config", default=None, help="Path to config YAML")
    run.add_argument(
        "--workspace",
        default=None,
        help="Directory for cloned repos (default: ~/.aiorchestra/workspaces)",
    )
    run.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    run.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Verbosity: -v INFO, -vv DEBUG, -vvv firehose",
    )
    run.add_argument(
        "--watch", action="store_true", help="Run continuously, polling for new issues"
    )
    run.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        help="Seconds between scans in watch mode (default: 300)",
    )

    dispatch = sub.add_parser(
        "dispatch",
        help="Scan all owned repos for 'aiorchestra'-labeled issues",
    )
    dispatch.add_argument(
        "--owner",
        default="@me",
        help="GitHub owner to scan (default: @me, i.e. the authenticated user)",
    )
    dispatch.add_argument("--config", default=None, help="Path to config YAML")
    dispatch.add_argument(
        "--workspace",
        default=None,
        help="Directory for cloned repos (default: ~/.aiorchestra/workspaces)",
    )
    dispatch.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    dispatch.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Verbosity: -v INFO, -vv DEBUG, -vvv firehose",
    )
    dispatch.add_argument(
        "--watch", action="store_true", help="Run continuously, polling for new issues"
    )
    dispatch.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        help="Seconds between scans in watch mode (default: 300)",
    )

    setup = sub.add_parser(
        "setup-labels",
        help="Create AIOrchestra labels in one or more GitHub repos",
    )
    setup.add_argument(
        "repos",
        nargs="+",
        help="GitHub repos (owner/repo) to create labels in",
    )
    setup.add_argument("--dry-run", action="store_true", help="Show what would be created")
    setup.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Verbosity: -v INFO, -vv DEBUG, -vvv firehose",
    )

    return parser


def _resolve_poll_interval(args: argparse.Namespace, config: dict) -> int:
    if args.poll_interval is not None:
        return args.poll_interval
    return config.get("watch", {}).get("poll_interval", 300)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    setup_logging(verbosity=getattr(args, "verbose", 0))

    if args.command == "run":
        config = load_config(args.config)
        _init_sentry(config)
        pipeline = Pipeline(
            repo=args.repo,
            label=args.label or config.get("label", "claude"),
            issue_number=args.issue,
            config=config,
            config_path=args.config,
            dry_run=args.dry_run,
            workspace=args.workspace,
        )
        if args.watch:
            return _watch_loop(pipeline.run, _resolve_poll_interval(args, config))
        return pipeline.run()

    if args.command == "dispatch":
        config = load_config(args.config)
        _init_sentry(config)
        dispatcher = Dispatcher(
            config=config,
            owner=args.owner,
            config_path=args.config,
            dry_run=args.dry_run,
            workspace=args.workspace,
        )
        if args.watch:
            return _watch_loop(dispatcher.run, _resolve_poll_interval(args, config))
        return dispatcher.run()

    if args.command == "setup-labels":
        total_created = 0
        for repo in args.repos:
            log.info("Setting up labels in %s …", repo)
            created = ensure_labels(repo, dry_run=args.dry_run)
            if created:
                log.info("Created %d label(s) in %s: %s", len(created), repo, ", ".join(created))
            else:
                log.info("All labels already exist in %s", repo)
            total_created += len(created)
        log.info("Done — %d label(s) created across %d repo(s)", total_created, len(args.repos))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
