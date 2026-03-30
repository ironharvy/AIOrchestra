"""CLI entry point for AIOrchestra."""

import argparse
import logging
import sys

from aiorchestra.config import load_config
from aiorchestra.pipeline import Pipeline


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
    run.add_argument("--workspace", default=None,
                     help="Directory for cloned repos (default: ~/.aiorchestra/workspaces)")
    run.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    run.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "run":
        config = load_config(args.config)
        pipeline = Pipeline(
            repo=args.repo,
            label=args.label or config.get("label", "claude"),
            issue_number=args.issue,
            config=config,
            dry_run=args.dry_run,
            workspace=args.workspace,
        )
        return pipeline.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
