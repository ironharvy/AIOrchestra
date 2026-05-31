"""CLI entry point for AIOrchestra."""

import argparse
import logging
import signal
import sys
import time
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version

from aiorchestra._logging import setup_logging
from aiorchestra._sentry import init as _init_sentry
from aiorchestra.config import load_config
from aiorchestra.dispatcher import Dispatcher
from aiorchestra.pipeline import Pipeline
from aiorchestra.stages.labels import ensure_labels

log = logging.getLogger(__name__)


def _version() -> str:
    try:
        return version("aiorchestra")
    except PackageNotFoundError:  # pragma: no cover - editable/uninstalled checkout
        return "0.0.0+unknown"


_MAIN_DESCRIPTION = """\
Orchestrate AI coding agents with deterministic shell automation.

AIOrchestra drives GitHub issues through a five-stage pipeline, handing the
creative work to an AI agent (Claude, Codex, Gemini, Jules, or OpenCode) while
keeping every shell command, validation, and git operation under deterministic
control:

  discover  -> read the issue and plan the change
  implement -> let the AI agent edit the code on a fresh branch
  validate  -> run the repo's lint/test commands until they pass
  review    -> have the agent self-review the diff
  publish   -> commit, push, and open a pull request

Pick a command below and pass -h to it (e.g. `aiorchestra run -h`) for the
full set of options."""

_MAIN_EPILOG = """\
examples:
  # Process every open, labeled issue in one repo, auto-routing each to its agent
  aiorchestra run --repo owner/repo

  # Work a single issue with a specific agent, previewing the plan first
  aiorchestra run --repo owner/repo --issue 42 --label claude --dry-run

  # Re-validate and review work already pushed to the branch (no new edits)
  aiorchestra run --repo owner/repo --issue 42 --review-only

  # Continuously poll a repo for new issues every 2 minutes
  aiorchestra run --repo owner/repo --watch --poll-interval 120

  # Scan every repo you own for 'aiorchestra'-labeled issues
  aiorchestra dispatch --owner @me

  # Create the AIOrchestra issue labels in one or more repos
  aiorchestra setup-labels owner/repo owner/other-repo"""

# Shared help sections appended to each command's epilog so that `-h` on any
# subcommand documents the full set of supported knobs, not just its flags.
_LOGGING_HELP = """\
logging & verbosity:
  Logs stream to stderr. The default level is WARNING; add -v to raise it:
    (none)   WARNING  errors and warnings only
    -v       INFO     high-level progress (per issue, per stage)
    -vv      DEBUG    detailed internal state
    -vvv     DEBUG + unmute noisy third-party libraries (httpx, urllib3, …)
  Output is colored text on a terminal and newline-delimited JSON when piped
  or redirected. --log-file additionally tees structured JSON logs to a file
  (its parent directories are created automatically)."""

_ENV_HELP = """\
environment variables:
  LOG_LEVEL                  Force a log level (DEBUG/INFO/WARNING/ERROR),
                             overriding any -v/-vv/-vvv flags.
  LOG_FORMAT                 Force stderr format: 'json' or 'text'
                             (default: auto — text on a TTY, JSON otherwise).
  AIORCHESTRA_LOG_FILE       Default --log-file path (LOG_FILE also honored).
  SENTRY_DSN                 Enable Sentry error reporting (or set sentry.dsn).
  SENTRY_ENVIRONMENT         Sentry environment tag (default: production).
  SENTRY_TRACES_SAMPLE_RATE  Sentry trace sampling rate, 0.0–1.0.

configuration:
  Settings merge in order: built-in defaults, the target repo's
  .aiorchestra/config.yaml, then --config (or an auto-detected
  ./aiorchestra.yaml). Use --dry-run to print the resolved plan without
  touching any repository."""


def _command_epilog(examples: str) -> str:
    """Compose a subcommand epilog from its examples plus the shared sections."""
    return f"{examples}\n\n{_LOGGING_HELP}\n\n{_ENV_HELP}"


def _add_logging_args(parser: argparse.ArgumentParser, *, default_log_file: str) -> None:
    """Add the --verbose/--log-file flags shared by every subcommand."""
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help=(
            "Increase log verbosity (repeatable): -v INFO, -vv DEBUG, "
            "-vvv DEBUG + third-party libs. Default is WARNING. "
            "Overridden by $LOG_LEVEL. See 'logging & verbosity' below."
        ),
    )
    parser.add_argument(
        "--log-file",
        default=default_log_file,
        metavar="PATH",
        help=(
            "Tee structured JSON logs to this file in addition to stderr "
            "(default: %(default)s). Overrides $AIORCHESTRA_LOG_FILE / $LOG_FILE."
        ),
    )


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
        description=_MAIN_DESCRIPTION,
        epilog=_command_epilog(_MAIN_EPILOG),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_version()}",
        help="Show the installed AIOrchestra version and exit",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    run = sub.add_parser(
        "run",
        help="Process issues and drive the AI pipeline",
        description=(
            "Run the full discover -> implement -> validate -> review -> publish "
            "pipeline against the issues in a single repository."
        ),
        epilog=_command_epilog(
            "examples:\n"
            "  aiorchestra run --repo owner/repo\n"
            "  aiorchestra run --repo owner/repo --issue 42 --label claude --dry-run\n"
            "  aiorchestra run --repo owner/repo --review-only\n"
            "  aiorchestra run --repo owner/repo --watch --poll-interval 120"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.add_argument(
        "--repo", required=True, metavar="OWNER/REPO", help="GitHub repository to process"
    )
    run.add_argument(
        "--label",
        default=None,
        metavar="AGENT",
        help=(
            "Pin a specific agent family (claude, codex, gemini, jules, opencode). "
            "When omitted, each issue is auto-routed to the agent implied by its labels."
        ),
    )
    run.add_argument(
        "--issue", type=int, default=None, metavar="N", help="Process only this issue number"
    )
    run.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to a config YAML (default: auto-detect ./aiorchestra.yaml)",
    )
    run.add_argument(
        "--workspace",
        default=None,
        metavar="DIR",
        help="Directory for cloned repos (default: ~/.aiorchestra/workspaces)",
    )
    run.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    run.add_argument(
        "--review-only",
        action="store_true",
        help="Skip implementation — only validate and review existing work on the branch",
    )
    run.add_argument(
        "--watch", action="store_true", help="Run continuously, polling for new issues"
    )
    run.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Seconds between scans in watch mode (default: 300)",
    )
    _add_logging_args(run, default_log_file=".log/aiorchestra-run.log")

    dispatch = sub.add_parser(
        "dispatch",
        help="Scan all owned repos for 'aiorchestra'-labeled issues",
        description=(
            "Discover every repository owned by --owner, then run the pipeline "
            "against each one that has open 'aiorchestra'-labeled issues."
        ),
        epilog=_command_epilog(
            "examples:\n"
            "  aiorchestra dispatch\n"
            "  aiorchestra dispatch --owner myorg --dry-run\n"
            "  aiorchestra dispatch --watch --poll-interval 600"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    dispatch.add_argument(
        "--owner",
        default="@me",
        metavar="OWNER",
        help="GitHub owner to scan (default: @me, i.e. the authenticated user)",
    )
    dispatch.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to a config YAML (default: auto-detect ./aiorchestra.yaml)",
    )
    dispatch.add_argument(
        "--workspace",
        default=None,
        metavar="DIR",
        help="Directory for cloned repos (default: ~/.aiorchestra/workspaces)",
    )
    dispatch.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    dispatch.add_argument(
        "--watch", action="store_true", help="Run continuously, polling for new issues"
    )
    dispatch.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Seconds between scans in watch mode (default: 300)",
    )
    _add_logging_args(dispatch, default_log_file=".log/aiorchestra-dispatch.log")

    setup = sub.add_parser(
        "setup-labels",
        help="Create AIOrchestra labels in one or more GitHub repos",
        description=(
            "Create the labels AIOrchestra uses to discover and route issues "
            "(e.g. 'aiorchestra' and the per-agent labels) in each given repo. "
            "Existing labels are left untouched."
        ),
        epilog=_command_epilog(
            "examples:\n"
            "  aiorchestra setup-labels owner/repo\n"
            "  aiorchestra setup-labels owner/repo owner/other-repo --dry-run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    setup.add_argument(
        "repos",
        nargs="+",
        metavar="OWNER/REPO",
        help="One or more GitHub repos to create labels in",
    )
    setup.add_argument("--dry-run", action="store_true", help="Show what would be created")
    _add_logging_args(setup, default_log_file=".log/aiorchestra-setup-labels.log")

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

    setup_logging(
        verbosity=getattr(args, "verbose", 0),
        log_file=getattr(args, "log_file", None),
    )

    if args.command == "run":
        config = load_config(args.config)
        _init_sentry(config)
        pipeline = Pipeline(
            repo=args.repo,
            label=args.label or config.get("label"),
            issue_number=args.issue,
            config=config,
            config_path=args.config,
            dry_run=args.dry_run,
            workspace=args.workspace,
            review_only=args.review_only,
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
