"""tool-usage subcommand: aggregate tool invocations across transcripts.

Reports per-tool, per-MCP-server, and per-agent call counts over a time
window, including MCP servers that were available but never called.

Exit codes:
    0  Success — JSON written to stdout.
    1  IO failure — the data directory could not be read.
    2  Invalid window — the resolved --from/--to bounds are inverted
       (from_date >= to_date).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_prospector.aggregator import compute_tool_usage
from claude_prospector.cli.dashboard import _parse_date
from claude_prospector.parser import parse_sessions
from claude_prospector.tool_collection import collect_per_session

EXIT_OK = 0
EXIT_IO_FAILURE = 1
EXIT_INVALID_WINDOW = 2

DEFAULT_DAYS: int = 7


def build_parser(parent: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the 'tool-usage' subparser and return it.

    Args:
        parent: The subparsers action from the top-level parser.

    Returns:
        The configured tool-usage ArgumentParser.
    """
    p = parent.add_parser(
        "tool-usage",
        help="Aggregate tool and MCP-server usage across Claude Code sessions.",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".claude",
        help="Claude data directory (default: ~/.claude).",
    )
    p.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Include sessions from the last N days (default: {DEFAULT_DAYS}).",
    )
    p.add_argument(
        "--from",
        dest="from_date",
        type=_parse_date,
        default=None,
        help="Include sessions on or after this date (YYYY-MM-DD). Overrides --days.",
    )
    p.add_argument(
        "--to",
        dest="to_date",
        type=_parse_date,
        default=None,
        help="Include sessions before this date (YYYY-MM-DD).",
    )
    p.add_argument("--repo", default=None, help="Only sessions in this project.")
    p.add_argument(
        "--agent",
        default=None,
        help="Only calls made by this agent (matches any segment of the agent path).",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--tool", default=None, help="Glob over raw tool names.")
    group.add_argument(
        "--server",
        default=None,
        help="Only calls to this MCP server (exact match, e.g. 'azure').",
    )
    p.add_argument(
        "--compact",
        action="store_true",
        help="Report by_agent keyed by MCP server with a single _builtin bucket.",
    )
    p.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format. JSON is the only supported format.",
    )
    return p


def _window_bounds(
    args: argparse.Namespace,
) -> tuple[datetime | None, datetime | None]:
    """Resolve the session-selection window.

    Args:
        args: Parsed CLI arguments.

    Returns:
        A ``(from_date, to_date)`` pair; either may be None.
    """
    if args.from_date is not None:
        return args.from_date, args.to_date
    if args.days is not None and args.days > 0:
        if args.to_date is not None:
            return args.to_date - timedelta(days=args.days), args.to_date
        return datetime.now(timezone.utc) - timedelta(days=args.days), args.to_date
    return None, args.to_date


def run(args: argparse.Namespace) -> int:
    """Run the tool-usage subcommand.

    Args:
        args: Parsed CLI arguments.

    Returns:
        EXIT_OK on success, EXIT_IO_FAILURE when the data directory is
        unreadable, EXIT_INVALID_WINDOW when the resolved --from/--to
        window is inverted or empty.
    """
    from_date, to_date = _window_bounds(args)
    if from_date is not None and to_date is not None and from_date >= to_date:
        print(
            "Invalid date window: --from "
            f"({from_date.date().isoformat()}) is not before --to "
            f"({to_date.date().isoformat()}); the from/to range must "
            "not be empty or inverted.",
            file=sys.stderr,
        )
        return EXIT_INVALID_WINDOW

    try:
        sessions = parse_sessions(args.data_dir)
    except OSError as exc:
        print(f"Could not read {args.data_dir}: {exc}", file=sys.stderr)
        return EXIT_IO_FAILURE

    selected = [
        session
        for session in sessions
        if (args.repo is None or session.project == args.repo)
        and (from_date is None or session.start_time >= from_date)
        and (to_date is None or session.start_time < to_date)
    ]
    per_session, skipped = collect_per_session(
        selected,
        args.data_dir,
        agent=args.agent,
        tool=args.tool,
        server=args.server,
    )

    report = compute_tool_usage(per_session, compact=args.compact)
    report["window"] = {
        "start": from_date.date().isoformat() if from_date else None,
        "end": to_date.date().isoformat() if to_date else None,
        "sessions": len(per_session),
        "sessions_skipped": skipped,
    }
    report["compact"] = bool(args.compact)
    report["warnings"]["unreadable_transcripts"] = skipped

    print(json.dumps(report, indent=2))
    return EXIT_OK
