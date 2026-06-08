"""CLI entry point for claude-prospector — subparser dispatcher."""

from __future__ import annotations

import sys

import claude_prospector
from claude_prospector.cli import (
    audit,
    config,
    dashboard,
    drift_report,
    session_audit,
    session_summary,
    variance_save,
)


def main() -> None:
    """Parse top-level subcommand and dispatch to the appropriate runner."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="claude-prospector",
        description=(
            "Claude Code token usage tools. "
            "Run 'claude-prospector <subcommand> --help' for details."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"claude-prospector {claude_prospector.__version__}",
    )
    subparsers = parser.add_subparsers(
        dest="subcommand",
        metavar="subcommand",
    )

    dashboard.build_parser(subparsers)
    session_summary.build_parser(subparsers)
    session_audit.build_parser(subparsers)
    config.build_parser(subparsers)
    audit.build_parser(subparsers)
    variance_save.build_parser(subparsers)
    drift_report.build_parser(subparsers)

    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    if args.subcommand == "dashboard":
        sys.exit(dashboard.run(args))

    if args.subcommand == "session-summary":
        sys.exit(session_summary.run(args))

    if args.subcommand == "session-audit":
        sys.exit(session_audit.run(args))

    if args.subcommand == "config":
        sys.exit(config.run(args))

    if args.subcommand == "audit":
        sys.exit(audit.run(args))

    if args.subcommand == "variance-save":
        sys.exit(variance_save.run(args))

    if args.subcommand == "drift-report":
        sys.exit(drift_report.run(args))


if __name__ == "__main__":
    main()
