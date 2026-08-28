"""Dashboard subcommand for claude-prospector."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_prospector.aggregator import aggregate
from claude_prospector.parser import parse_sessions
from claude_prospector.renderer import render
from claude_prospector.skill_tracking import parse_skill_tracking


def _parse_window(window_str: str) -> float:
    """Parse a window string like '5h' or '7d' into hours.

    Args:
        window_str: A string of the form '<number>h' or '<number>d'.

    Returns:
        The window duration expressed as a float number of hours.

    Raises:
        argparse.ArgumentTypeError: If the format is not recognised.
    """
    match = re.match(r"^(\d+(?:\.\d+)?)(h|d)$", window_str.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(
            f"Invalid window format: '{window_str}'. Use e.g. '5h' or '7d'."
        )
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "d":
        value *= 24
    return value


def _parse_date(date_str: str) -> datetime:
    """Parse a date string (YYYY-MM-DD) into a timezone-aware datetime.

    Args:
        date_str: A date string in YYYY-MM-DD format.

    Returns:
        A UTC-aware datetime set to midnight on the given date.

    Raises:
        argparse.ArgumentTypeError: If the string is not YYYY-MM-DD.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: '{date_str}'. Use YYYY-MM-DD."
        )


def build_parser(parent: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the 'dashboard' subparser and return it.

    Args:
        parent: The subparsers action from the top-level parser.

    Returns:
        The configured dashboard ArgumentParser.
    """
    p = parent.add_parser(
        "dashboard",
        help="Generate an HTML or JSON dashboard of Claude Code token usage.",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".claude",
        help=("Path to Claude Code data directory (default: ~/.claude)"),
    )
    p.add_argument(
        "--from",
        dest="from_date",
        type=_parse_date,
        help=("Start date (YYYY-MM-DD). Only include data on or after this date."),
    )
    p.add_argument(
        "--to",
        dest="to_date",
        type=_parse_date,
        help=("End date (YYYY-MM-DD). Only include data before this date."),
    )
    p.add_argument(
        "--window",
        type=_parse_window,
        help="Rolling window (e.g. '5h', '7d'). Overrides --from.",
    )
    p.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output file path. If omitted, writes to a temp file.",
    )
    p.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open the dashboard in a browser.",
    )
    p.add_argument(
        "--limit-5h",
        type=int,
        default=None,
        help="Token budget for 5-hour rolling window.",
    )
    p.add_argument(
        "--limit-7d",
        type=int,
        default=None,
        help="Token budget for 7-day rolling window.",
    )
    p.add_argument(
        "--limit-sonnet-7d",
        type=int,
        default=None,
        help="Token budget for Sonnet-only 7-day window.",
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["html", "json"],
        default="html",
        help=(
            "Output format: 'html' (default) opens a dashboard; "
            "'json' writes structured data to stdout."
        ),
    )
    p.add_argument(
        "--track-mcp-calls",
        action="store_true",
        default=False,
        help=(
            "Collect MCP tool-call usage data (by_mcp_usage). Reads every "
            "in-window session's transcript a second time, so this adds "
            "extra IO cost on top of the default aggregation."
        ),
    )
    p.add_argument(
        "--track-mcp-call-sizes",
        action="store_true",
        default=False,
        help=(
            "Reserved for an upcoming per-call token-cost proxy for MCP "
            "tool calls, estimated from the character length of each "
            "call's result. Parsed now but not yet wired up -- has no "
            "effect on collection or reporting until a later release "
            "ships it. Once active, it will temporarily read tool_result "
            "payload data that is otherwise never touched -- length "
            "only, computed and discarded, never persisted or logged as "
            "content. A privacy-posture opt-in, independent of "
            "--track-mcp-calls (which stays call-counts-only)."
        ),
    )
    return p


def run(args: argparse.Namespace) -> int:
    """Execute the dashboard subcommand.

    Args:
        args: Parsed argument namespace from the dashboard subparser.

    Returns:
        Integer exit code (0 on success).
    """
    # In json mode, status messages go to stderr so stdout carries only the JSON payload.
    status_file = sys.stderr if args.output_format == "json" else sys.stdout

    print(f"Scanning sessions in {args.data_dir}...", file=status_file)
    sessions = parse_sessions(args.data_dir)
    print(f"Found {len(sessions)} sessions.", file=status_file)

    # Resolve --window/--from/--to once, up front, so aggregate() and the
    # by_mcp_usage.window block below are guaranteed to agree on the same
    # bounds (D-C finding-2: resolving --window inside aggregate() only,
    # and separately passing raw args.from_date elsewhere, is how that bug
    # class happens).
    resolved_from = args.from_date
    resolved_to = args.to_date
    if args.window is not None:
        resolved_from = datetime.now(timezone.utc) - timedelta(hours=args.window)
        resolved_to = None

    result = aggregate(
        sessions,
        from_date=resolved_from,
        to_date=resolved_to,
        window_hours=None,
    )
    print(
        f"Aggregated: {result.total_tokens:,} tokens across {result.total_sessions} sessions.",
        file=status_file,
    )

    # Skill adoption tracking (from PreToolUse hook log)
    passed_events, invoked_events = parse_skill_tracking(args.data_dir)
    if passed_events or invoked_events:
        from claude_prospector.aggregator import compute_skill_adoption

        result.by_skill_adoption = compute_skill_adoption(
            passed_events,
            invoked_events,
            from_date=resolved_from,
            to_date=resolved_to,
        )

    if args.track_mcp_calls:
        from claude_prospector.aggregator import compute_tool_usage
        from claude_prospector.tool_collection import collect_per_session

        in_window = {s["session_id"] for s in result.sessions}  # D-B(a)
        selected = [s for s in sessions if s.session_id in in_window]
        # data_dir is required -- the helper owns the projects/*.jsonl glob.
        # No agent/tool/server filters from the dashboard.
        per_session, skipped = collect_per_session(selected, args.data_dir)
        usage = compute_tool_usage(per_session)  # compact=False
        usage.pop("by_agent", None)  # D-F(a) RESOLVED -- absent, not {}
        usage["warnings"]["unreadable_transcripts"] = skipped
        usage["window"] = {  # D-K / plan §4.3
            "start": resolved_from.date().isoformat() if resolved_from else None,
            "end": resolved_to.date().isoformat() if resolved_to else None,
            "sessions": len(per_session),
            "sessions_skipped": skipped,
        }
        result.by_mcp_usage = usage

    limits = None
    if any([args.limit_5h, args.limit_7d, args.limit_sonnet_7d]):
        limits = {
            "limit_5h": args.limit_5h,
            "limit_7d": args.limit_7d,
            "limit_sonnet_7d": args.limit_sonnet_7d,
        }

    # Resolve default --output path.  The argparse default is None so that
    # render() can distinguish "caller omitted --output" (use temp file) from
    # an explicit path.  When $CLAUDE_PLUGIN_DATA is set we resolve a
    # persistent, plugin-owned location here in the handler; otherwise we
    # leave output_path as None and let render() pick a temp file.
    output_path: Path | None = args.output
    if output_path is None:
        plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        if plugin_data:
            output_path = Path(plugin_data) / "dashboard.html"

    if args.output_format == "json":
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_tokens": result.total_tokens,
            "total_messages": result.total_messages,
            "total_sessions": result.total_sessions,
            "by_model": result.by_model,
            "by_agent": result.by_agent,
            "by_skill": result.by_skill,
            "by_project": result.by_project,
            "by_day": result.by_day,
            "sessions": result.sessions,
            "limits": limits,
            "by_skill_adoption": result.by_skill_adoption,
        }
        if args.track_mcp_calls:
            payload["by_mcp_usage"] = result.by_mcp_usage
        print(json.dumps(payload, indent=2))
        return 0

    output = render(
        result,
        output_path=output_path,
        open_browser=not args.no_open,
        limits=limits,
    )
    print(f"Dashboard written to {output}")
    return 0
