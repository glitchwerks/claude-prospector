"""Drift-report subcommand: aggregate drift frequency across variance records.

Reads all ``<base_dir>/variance/*.json`` records written by ``variance-save``,
filters to a configurable time window, and computes drift frequency, severity
distribution, and a per-day trend.

No LLM cost — purely deterministic aggregation.

JSON output schema (``--format json``, the default)::

    {
        "window": {
            "from": "<ISO-8601 UTC>",
            "to":   "<ISO-8601 UTC>"
        },
        "total_records":            <int>,
        "skipped_records":          <int>,
        "records_without_timestamp": <int>,
        "drift": {
            "drifted":    <int>,
            "clean":      <int>,
            "drift_rate": <float, 3 dp>
        },
        "severity_distribution": {
            "0": <int>, "1": <int>, "2": <int>,
            "3": <int>, "null": <int>
        },
        "trend": [
            {
                "date":       "YYYY-MM-DD",
                "total":      <int>,
                "drifted":    <int>,
                "drift_rate": <float, 3 dp>
            },
            ...
        ]
    }

Invariant: ``sum(severity_distribution.values()) == total_records``.

Exit codes:
    0  Success — JSON or text written to stdout.
    1  IO failure — unreadable variance directory or OS-level error.
       Records that fail ``json.loads`` are silently skipped (not IO failures).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from claude_prospector.cli.dashboard import _parse_date, _parse_window
from claude_prospector.paths import base_dir as _resolve_base_dir

EXIT_OK = 0
EXIT_IO_FAILURE = 1

# Internal sentinel constant used as a marker that a key was absent.
_ABSENT = object()

# Sentinel strings recognised as "no drift" in the prose fallback.
# Case-insensitive match; empty string (after strip) is also clean.
# Do NOT expand this set without verifying against real 1b skill output
# and updating the skill instructions in lockstep (see spec §5).
_CLEAN_SENTINELS: frozenset[str] = frozenset({"no variance"})


# ---------------------------------------------------------------------------
# Pure helpers — unit-testable, no I/O
# ---------------------------------------------------------------------------


def is_drifted(variance: str) -> bool:
    """Return True when a variance prose string indicates drift.

    This is the **null-severity fallback** used only when ``severity`` is
    null or absent.  The severity value is the authoritative drift signal
    when present (0 = clean; 1–3 = drifted); prose is not consulted then.

    A record is **clean** when its ``variance`` string, after ``.strip()``,
    is either the empty string or (case-insensitively) in
    :data:`_CLEAN_SENTINELS`.  Every other non-empty string is drifted.

    Args:
        variance: The ``variance`` field from a variance record.

    Returns:
        ``True`` when the record is drifted; ``False`` when clean.
    """
    stripped = variance.strip()
    if not stripped:
        return False
    return stripped.lower() not in _CLEAN_SENTINELS


def severity_bucket(severity: Any) -> str:
    """Map a severity value to its string bucket key.

    Valid values 0, 1, 2, 3 map to ``"0"``, ``"1"``, ``"2"``, ``"3"``.
    ``None``, absent (caller passes ``None``), or any out-of-range value
    maps to ``"null"``.  ``null`` is intentionally its own bucket — it is
    semantically distinct from "0, on task".

    Args:
        severity: Raw severity value from a variance record.  Typically
            ``int | None``; out-of-range values are also handled.

    Returns:
        One of ``"0"``, ``"1"``, ``"2"``, ``"3"``, or ``"null"``.
    """
    if severity in (0, 1, 2, 3):
        return str(severity)
    return "null"


def record_anchor_time(record: dict, file_mtime: float) -> datetime:
    """Return the UTC datetime to use as this record's time anchor.

    Uses the record's ``timestamp`` field (ISO-8601, tz-aware UTC) when
    present and non-null.  Falls back to ``file_mtime`` (a POSIX timestamp
    float) for legacy records that pre-date the ``timestamp`` field.

    The caller is responsible for tracking how many records needed the
    mtime fallback (via ``_mtime`` injection — see :func:`aggregate_drift`).

    Args:
        record: A parsed variance record dict.  May or may not contain a
            ``"timestamp"`` key.
        file_mtime: File modification time as a POSIX timestamp float
            (from ``Path.stat().st_mtime``).

    Returns:
        A tz-aware UTC :class:`datetime` for the record.
    """
    raw_ts = record.get("timestamp")
    if raw_ts:
        # Normalise Z → +00:00 for fromisoformat compatibility.
        normalised = raw_ts.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalised)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass  # fall through to mtime

    return datetime.fromtimestamp(file_mtime, tz=timezone.utc)


def aggregate_drift(
    records: list[dict],
    from_dt: datetime,
    to_dt: datetime,
) -> dict[str, Any]:
    """Aggregate drift statistics over *records* within [from_dt, to_dt).

    Applies severity-primary drift classification (§5):
    - ``severity`` in {1, 2, 3} → drifted.
    - ``severity == 0`` → clean.
    - ``severity`` null/absent → falls back to :func:`is_drifted` prose check.

    Drift rate is rounded to 3 decimal places; ``0.0`` when total is 0.

    Invariant: ``sum(severity_distribution.values()) == total_records``.

    Args:
        records: List of variance record dicts, each optionally containing
            a ``_mtime`` key (float) injected by :func:`load_variance_records`
            for the mtime fallback.
        from_dt: Start of the time window (inclusive, tz-aware UTC).
        to_dt: End of the time window (exclusive, tz-aware UTC).

    Returns:
        A dict matching the §4.1 JSON output shape.
    """
    dist: dict[str, int] = {"0": 0, "1": 0, "2": 0, "3": 0, "null": 0}

    # Per-day trend accumulator: date_str → {"total": int, "drifted": int}
    day_totals: dict[str, dict[str, int]] = {}

    # Enumerate all calendar days in [from_dt, to_dt).
    current = from_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if current < from_dt:
        current += timedelta(days=1)
    # Ensure we start from the date of from_dt.
    start_day = from_dt.replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=from_dt.tzinfo
    )
    # Walk every calendar day in [from_dt.date, to_dt.date)
    day_cursor = start_day
    while day_cursor < to_dt:
        day_key = day_cursor.strftime("%Y-%m-%d")
        day_totals[day_key] = {"total": 0, "drifted": 0}
        day_cursor += timedelta(days=1)

    total_records = 0
    drifted_count = 0
    without_timestamp = 0

    for rec in records:
        file_mtime: float = rec.get("_mtime", 0.0)
        anchor = record_anchor_time(rec, file_mtime)

        # Filter to window [from_dt, to_dt).
        if anchor < from_dt or anchor >= to_dt:
            continue

        # Track whether this record used the mtime fallback.
        if not rec.get("timestamp"):
            without_timestamp += 1

        total_records += 1

        # Severity-primary classification.
        severity = rec.get("severity", None)
        bucket = severity_bucket(severity)
        dist[bucket] += 1

        if severity in (1, 2, 3):
            is_drift = True
        elif severity == 0:
            is_drift = False
        else:
            # null / absent — prose fallback.
            is_drift = is_drifted(rec.get("variance", ""))

        if is_drift:
            drifted_count += 1

        # Accumulate into trend day bucket.
        day_key = anchor.strftime("%Y-%m-%d")
        if day_key in day_totals:
            day_totals[day_key]["total"] += 1
            if is_drift:
                day_totals[day_key]["drifted"] += 1

    # Build trend list (sorted, continuous — all days present).
    trend = []
    for day_key in sorted(day_totals):
        day = day_totals[day_key]
        d_total = day["total"]
        d_drifted = day["drifted"]
        d_rate = round(d_drifted / d_total, 3) if d_total else 0.0
        trend.append(
            {
                "date": day_key,
                "total": d_total,
                "drifted": d_drifted,
                "drift_rate": d_rate,
            }
        )

    drift_rate = round(drifted_count / total_records, 3) if total_records else 0.0

    return {
        "window": {
            "from": from_dt.isoformat(),
            "to": to_dt.isoformat(),
        },
        "total_records": total_records,
        "skipped_records": 0,  # populated by run() after load_variance_records
        "records_without_timestamp": without_timestamp,
        "drift": {
            "drifted": drifted_count,
            "clean": total_records - drifted_count,
            "drift_rate": drift_rate,
        },
        "severity_distribution": dist,
        "trend": trend,
    }


def render_text(report: dict) -> str:
    """Render a drift report dict as a plain ASCII text summary.

    Produces the §4.2 human-readable format: a header, session count,
    drift fraction, severity histogram, and a per-day trend bar chart.
    No ANSI colour, no Unicode — output is copy-pasteable plain text.

    When ``records_without_timestamp > 0``, appends a temporal-distortion
    warning line to the session count line.

    Args:
        report: A dict in the §4.1 JSON output shape as returned by
            :func:`aggregate_drift`.

    Returns:
        A multi-line ASCII string.
    """
    window = report["window"]
    # Extract just the date portion for the header (YYYY-MM-DD).
    from_date = window["from"][:10]
    to_date = window["to"][:10]

    total = report["total_records"]
    drifted = report["drift"]["drifted"]
    rate_pct = int(report["drift"]["drift_rate"] * 100)
    dist = report["severity_distribution"]
    without_ts = report["records_without_timestamp"]

    lines: list[str] = []
    lines.append(f"Drift report -- {from_date} to {to_date}")

    # Sessions analyzed line — with optional mtime warning.
    sessions_line = f"  Sessions analyzed:  {total}"
    if without_ts > 0:
        sessions_line += (
            f"   ({without_ts} dated by file mtime"
            " -- temporal position may be unreliable"
            " for pre-migration records)"
        )
    lines.append(sessions_line)

    lines.append(f"  Drifted:            {drifted} / {total}  ({rate_pct}%)")

    # Severity histogram.
    sev_parts = "  ".join(f"{k}:{dist[k]}" for k in ("0", "1", "2", "3", "null"))
    lines.append(f"  Severity:           {sev_parts}")
    lines.append("")
    lines.append("  Trend (drift rate by day):")

    for entry in report["trend"]:
        day = entry["date"][5:]  # MM-DD
        d_total = entry["total"]
        d_drifted = entry["drifted"]
        d_rate = entry["drift_rate"]

        if d_total == 0:
            lines.append(f"    {day}  (no sessions)")
        else:
            # ASCII bar: each '#' = 5% drift rate (max 20 chars wide).
            bar_len = min(20, int(d_rate * 20))
            bar = "#" * bar_len
            pct = int(d_rate * 100)
            lines.append(f"    {day}  {bar:<20}  {pct:3d}%  ({d_drifted}/{d_total})")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Loader — file I/O
# ---------------------------------------------------------------------------


class _RecordList(list):
    """List subclass carrying a ``_skipped`` count alongside the records.

    Used only by :func:`load_variance_records` to return the skipped count
    without changing the function signature.  Callers access the count via
    ``getattr(result, "_skipped", 0)``.
    """

    _skipped: int = 0


def load_variance_records(base_dir: Path) -> list[dict]:
    """Glob ``<base_dir>/variance/*.json`` and return parsed record dicts.

    Records that fail ``json.loads`` are silently skipped and counted via
    a ``_skipped`` attribute on the returned list subclass.  Callers
    should access the count via ``getattr(result, "_skipped", 0)``.

    Each successfully loaded dict has a ``_mtime`` key (float, POSIX
    timestamp) injected from the file's ``st_mtime`` so
    :func:`record_anchor_time` can use it as a fallback for legacy records
    lacking a ``timestamp`` field.

    An absent or unreadable ``variance/`` directory is not an error — it
    returns an empty list.  Only OS-level read failures on individual files
    that *do* exist are propagated.

    Args:
        base_dir: Root directory whose ``variance/`` sub-directory is
            scanned.

    Returns:
        A :class:`_RecordList` (subclass of ``list``) of parsed record
        dicts, each with ``_mtime`` injected.  The list carries a
        ``_skipped`` attribute (int) counting parse failures.
    """
    variance_dir = base_dir / "variance"
    result = _RecordList()

    if not variance_dir.is_dir():
        return result

    for json_file in sorted(variance_dir.glob("*.json")):
        stat = json_file.stat()
        try:
            raw = json_file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            result._skipped += 1
            continue
        # Inject file mtime for records without a timestamp field.
        data["_mtime"] = stat.st_mtime
        result.append(data)

    return result


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def build_parser(
    parent: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    """Register the 'drift-report' subparser and return it.

    ``--window`` and ``--from/--to`` form a mutually exclusive group;
    ``--window`` defaults to ``7d`` (168 hours).  Both limits are
    validated in :func:`run`:

    - ``from_dt >= to_dt`` → error.
    - ``(to_dt - from_dt).days > 366`` → error.

    Args:
        parent: The subparsers action from the top-level argument parser.

    Returns:
        The configured drift-report ArgumentParser.
    """
    p = parent.add_parser(
        "drift-report",
        help=(
            "Aggregate drift frequency, severity distribution, and trend "
            "across variance records in <base_dir>/variance/."
        ),
    )

    # Mutually exclusive: --window vs --from/--to.
    window_group = p.add_mutually_exclusive_group()
    window_group.add_argument(
        "--window",
        dest="window",
        type=_parse_window,
        default=None,
        metavar="WINDOW",
        help=(
            "Relative time window, e.g. '7d' or '48h' (default: 7d). "
            "Maximum effective range is 366 days. "
            "Mutually exclusive with --from/--to."
        ),
    )
    window_group.add_argument(
        "--from",
        dest="from_date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Absolute start date (inclusive). "
            "Requires --to or defaults to now. "
            "Mutually exclusive with --window. "
            "Range must not exceed 366 days."
        ),
    )

    p.add_argument(
        "--to",
        dest="to_date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Absolute end date (exclusive). "
            "Defaults to now when --from is given without --to."
        ),
    )

    p.add_argument(
        "--format",
        dest="format",
        choices=("json", "text"),
        default="json",
        help="Output format: 'json' (default, machine-readable) or 'text'.",
    )

    p.add_argument(
        "--base-dir",
        dest="base_dir",
        type=Path,
        default=None,
        help=(
            "Override the variance-records root directory.  "
            "Defaults to the plugin data base dir resolved from "
            "CLAUDE_PROSPECTOR_BASE_DIR > CLAUDE_PLUGIN_DATA > "
            "~/.claude/claude-prospector."
        ),
    )

    return p


def run(args: argparse.Namespace) -> int:
    """Entry point for the drift-report subcommand.

    Resolves the time window, loads variance records, aggregates drift
    statistics, and prints JSON or text output to stdout.

    Args:
        args: Parsed CLI namespace.  Expected attributes:
            ``args.window`` (float hours or None),
            ``args.from_date`` (datetime or None),
            ``args.to_date`` (datetime or None),
            ``args.format`` (str: 'json' or 'text'),
            ``args.base_dir`` (Path or None).

    Returns:
        Integer exit code (``EXIT_OK`` on success, ``EXIT_IO_FAILURE`` on
        unrecoverable I/O error).
    """
    now = datetime.now(timezone.utc)

    # Resolve time window.
    window_val: float | None = getattr(args, "window", None)
    from_date: datetime | None = getattr(args, "from_date", None)
    to_date: datetime | None = getattr(args, "to_date", None)

    if from_date is not None:
        # --from / --to path.
        from_dt = from_date
        to_dt = to_date if to_date is not None else now
    else:
        # --window path (or unset → default 7d).
        window_hours: float = window_val if window_val is not None else 7 * 24
        from_dt = now - timedelta(hours=window_hours)
        to_dt = now

    # Validate range.
    if from_dt >= to_dt:
        print(
            "drift-report: invalid range: --from must precede --to",
            file=sys.stderr,
        )
        return EXIT_IO_FAILURE

    if (to_dt - from_dt).days > 366:
        print(
            "drift-report: window exceeds 366 days -- use a narrower range",
            file=sys.stderr,
        )
        return EXIT_IO_FAILURE

    # Resolve base directory.
    effective_base: Path = (
        args.base_dir if args.base_dir is not None else _resolve_base_dir()
    )

    # Load records.
    try:
        records = load_variance_records(effective_base)
    except OSError as exc:
        print(
            f"drift-report: I/O error reading variance dir: {exc}",
            file=sys.stderr,
        )
        return EXIT_IO_FAILURE

    skipped: int = getattr(records, "_skipped", 0)

    # Aggregate.
    report = aggregate_drift(records, from_dt, to_dt)
    report["skipped_records"] = skipped

    # Emit output.
    fmt: str = getattr(args, "format", "json")
    if fmt == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_text(report), end="")

    return EXIT_OK
