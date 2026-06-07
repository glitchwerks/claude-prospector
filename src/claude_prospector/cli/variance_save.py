"""Variance-save subcommand: persist 1a audit data merged with judgment.

Combines the deterministic output from the ``session-audit`` 1a extraction
(``original_ask``, ``prior_asks``, ``actions``) with caller-supplied
judgment fields (``variance``, ``not_done``, ``severity``) and writes a
single combined JSON artifact to ``<base_dir>/variance/<session_id>.json``.

The skill that calls this command is responsible for sourcing the judgment
fields from LLM-assisted analysis.  This module is **purely deterministic**:
it reads an existing transcript via :func:`audit_session`, merges the
judgment, and persists the result.

Root directories
----------------
Two roots are resolved **independently**:

Transcript search root (``--data-dir``)
    The root of the Claude data directory used to locate the session
    transcript.  Transcripts live at
    ``<data-dir>/projects/<project>/<session-id>.jsonl``.  Defaults to
    ``~/.claude`` — the same default used by the Claude Code client and
    the ``session-audit`` subcommand.  Pass ``--data-dir <path>`` to
    override (useful in tests or non-standard installations).

Variance output root
    Where the combined JSON is written.  Defaults to
    ``<base_dir>/variance/<session_id>.json`` where ``base_dir()`` is the
    plugin-data directory (``CLAUDE_PROSPECTOR_BASE_DIR`` >
    ``CLAUDE_PLUGIN_DATA`` > ``~/.claude/claude-prospector``).  Use
    ``--out <path>`` to override the output location entirely.

This decoupling means that
``variance-save --session-id <id> --judgment-file <f>`` works with **no
extra flags**: the transcript is found under ``~/.claude/projects/`` and
the record is written to ``<plugin-base>/variance/<id>.json``.

Combined JSON schema::

    {
        "session_id":   "<str>",
        "original_ask": "<str | null>",
        "prior_asks":   ["<str>", ...],
        "actions":      [{"tool": "<Edit|Write|NotebookEdit>",
                          "file_path": "<str>"}, ...],
        "variance":     "<str>",
        "not_done":     "<str>",
        "severity":     <int | null>,
        "timestamp":    "<ISO-8601 UTC str | null>"
    }

Fields:
    session_id:
        The Claude Code session identifier passed by the caller.
    original_ask:
        Verbatim first external user message, or ``null``.
    prior_asks:
        List of subsequent external user messages, in order.
    actions:
        Chronologically ordered Edit/Write/NotebookEdit tool_use events.
    variance:
        Human/LLM judgment describing what was done that was NOT asked.
        Required.
    not_done:
        Human/LLM judgment describing what was asked but NOT done.
        Required.
    severity:
        Integer severity rating (caller-defined scale), or ``null``.
        Optional.
    timestamp:
        ISO-8601 UTC string of the earliest transcript entry that carries
        a top-level ``"timestamp"`` key, or ``null`` when no such entry
        exists.  Derived from the raw transcript entries at write time.

Exit codes:
    0  Success — path of written file printed to stdout.
    1  IO failure — transcript missing, judgment unreadable, or OSError.
    2  Validation failure — malformed or incomplete judgment JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_prospector.cli.session_audit import (
    audit_session,
    resolve_session_id_to_path,
)
from claude_prospector.cli.session_summary import read_transcript
from claude_prospector.paths import base_dir as _resolve_base_dir

EXIT_OK = 0
EXIT_IO_FAILURE = 1
EXIT_VALIDATION_FAILURE = 2

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

JudgmentDict = dict[str, Any]
VarianceRecord = dict[str, Any]

# ---------------------------------------------------------------------------
# Timestamp derivation — pure helper, no I/O
# ---------------------------------------------------------------------------


def _earliest_transcript_timestamp(
    entries: list[dict],
) -> str | None:
    """Derive the earliest timestamp from raw transcript entry dicts.

    Collects every top-level ``"timestamp"`` value found in *entries*,
    normalises each using the ``Z``→``+00:00`` substitution (mirroring
    ``parser._parse_timestamp``), takes the minimum, and returns it as
    an ISO-8601 UTC string.

    When no entry carries a ``"timestamp"`` key the function returns
    ``None`` — the aggregator's mtime fallback handles this at read time.

    The entries are **raw** ``json.loads`` dicts as returned by
    :func:`~claude_prospector.cli.session_summary.read_transcript`;
    they are not ``parser.Message`` objects.

    Args:
        entries: List of raw dicts parsed from a JSONL transcript.

    Returns:
        ISO-8601 UTC string for the earliest entry timestamp, or
        ``None`` when no entry carries a ``"timestamp"`` key.
    """
    ts_candidates = [e["timestamp"] for e in entries if "timestamp" in e]
    if not ts_candidates:
        return None

    # Normalise each candidate string (Z → +00:00) and parse to datetime.
    parsed: list[datetime] = []
    for raw_ts in ts_candidates:
        normalised = raw_ts.replace("Z", "+00:00")
        try:
            parsed.append(datetime.fromisoformat(normalised))
        except ValueError:
            # Malformed timestamp — skip this entry.
            continue

    if not parsed:
        return None

    earliest = min(parsed)
    # Ensure result is UTC-aware and format as ISO-8601.
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)
    return earliest.isoformat()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REQUIRED_JUDGMENT_KEYS = ("variance", "not_done")


def validate_judgment(judgment: JudgmentDict) -> None:
    """Validate that a judgment dict contains all required keys.

    Args:
        judgment: Parsed judgment object from the caller.

    Raises:
        ValueError: When one or more required keys are absent.
    """
    missing = [k for k in _REQUIRED_JUDGMENT_KEYS if k not in judgment]
    if missing:
        raise ValueError(
            f"Judgment is missing required key(s): " f"{', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# Core combine logic — pure function, no I/O
# ---------------------------------------------------------------------------


def combine_variance(
    session_id: str,
    audit: dict[str, Any],
    judgment: JudgmentDict,
    timestamp: str | None = None,
) -> VarianceRecord:
    """Merge 1a audit data with judgment fields into the combined schema.

    Pure function — no I/O.  Callers are responsible for obtaining the
    audit data (via :func:`audit_session`) and a validated judgment dict
    (via :func:`validate_judgment`).

    ``severity`` defaults to ``None`` when absent from *judgment*.
    ``timestamp`` defaults to ``None`` (legacy path); pass the value
    returned by :func:`_earliest_transcript_timestamp` from
    :func:`save_variance_record` to populate the field.

    Args:
        session_id: The Claude Code session identifier.
        audit: Dict with keys ``original_ask``, ``prior_asks``,
            and ``actions`` (as returned by :func:`audit_session`).
        judgment: Dict with keys ``variance`` (str), ``not_done`` (str),
            and optionally ``severity`` (int or None).
        timestamp: ISO-8601 UTC string of the earliest transcript entry
            timestamp, or ``None`` when no entry carries a timestamp.
            Defaults to ``None`` so existing positional callers are
            unaffected.

    Returns:
        A combined :data:`VarianceRecord` dict matching the module-level
        JSON schema.
    """
    return {
        "session_id": session_id,
        "original_ask": audit.get("original_ask"),
        "prior_asks": audit.get("prior_asks", []),
        "actions": audit.get("actions", []),
        "variance": judgment["variance"],
        "not_done": judgment["not_done"],
        "severity": judgment.get("severity"),
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Session-id → path resolver (re-exported from session_audit)
# ---------------------------------------------------------------------------

# Re-export so callers and tests can import from a single place.
__all__ = [
    "build_parser",
    "combine_variance",
    "resolve_session_id_to_path",
    "run",
    "save_variance_record",
    "validate_judgment",
]


# ---------------------------------------------------------------------------
# Persist helper — the I/O layer
# ---------------------------------------------------------------------------


def save_variance_record(
    session_id: str,
    data_dir: Path,
    judgment: JudgmentDict,
    out_path: Path | None = None,
    out_base_dir: Path | None = None,
) -> Path:
    """Load 1a audit data, merge with judgment, and write the combined record.

    Resolves the transcript for *session_id* by calling
    :func:`resolve_session_id_to_path` against *data_dir* (the Claude
    data root, typically ``~/.claude``), then calls :func:`audit_session`
    on the parsed entries, merges with *judgment* via
    :func:`combine_variance`, and writes the result as UTF-8 JSON.

    The write is idempotent: an existing file for the same session-id is
    overwritten cleanly.

    Output path resolution (highest-priority first):

    1. *out_path* — explicit caller override.
    2. ``<out_base_dir>/variance/<session_id>.json`` — when *out_base_dir*
       is provided.
    3. ``<base_dir()>/variance/<session_id>.json`` — default using the
       :func:`~claude_prospector.paths.base_dir` plugin-data resolution.

    The ``variance/`` subdirectory is created automatically when absent.

    Note:
        *data_dir* and the output root are **independent**.  *data_dir*
        is used only to locate the session transcript; it does **not**
        influence where the combined record is written.

    Args:
        session_id: The Claude Code session identifier.
        data_dir: Root of the Claude data directory used to resolve the
            transcript (e.g. ``~/.claude``).  The transcript is expected
            at ``<data_dir>/projects/<project>/<session_id>.jsonl``.
        judgment: Pre-validated judgment dict with keys ``variance``,
            ``not_done``, and optionally ``severity``.
        out_path: Explicit override for the output file path.  When
            ``None`` the path is derived from *out_base_dir* (or
            ``base_dir()`` when *out_base_dir* is also ``None``).
        out_base_dir: Base directory for the default output path.  When
            ``None`` and *out_path* is also ``None``, :func:`base_dir`
            is called to resolve the plugin-data root.

    Returns:
        The resolved output path where the record was written.

    Raises:
        FileNotFoundError: When the session-id cannot be resolved.
        ValueError: When the session-id is ambiguous (multiple matches).
        OSError: On any I/O failure during read or write.
    """
    transcript_path = resolve_session_id_to_path(session_id, data_dir)
    entries, _non_blank = read_transcript(transcript_path)
    audit = audit_session(entries)

    # Derive earliest timestamp from raw entry dicts while `entries` is in
    # scope (raw json.loads dicts — not parser.Message objects).
    timestamp = _earliest_transcript_timestamp(entries)

    record = combine_variance(session_id, audit, judgment, timestamp=timestamp)

    if out_path is None:
        effective_base = (
            out_base_dir if out_base_dir is not None else _resolve_base_dir()
        )
        variance_dir = effective_base / "variance"
        variance_dir.mkdir(parents=True, exist_ok=True)
        out_path = variance_dir / f"{session_id}.json"
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)

    return out_path


# ---------------------------------------------------------------------------
# Judgment I/O — read from file or stdin
# ---------------------------------------------------------------------------


def _load_judgment(
    judgment_file: str | None,
) -> tuple[JudgmentDict | None, str | None]:
    """Load and parse the judgment JSON from a file or stdin.

    Reads from *judgment_file* when provided, otherwise reads from stdin.

    Args:
        judgment_file: Path string to a judgment JSON file, or ``None``
            to read from stdin.

    Returns:
        A tuple ``(judgment, error_message)``.  On success,
        ``judgment`` is the parsed dict and ``error_message`` is ``None``.
        On failure, ``judgment`` is ``None`` and ``error_message``
        describes the problem.
    """
    try:
        if judgment_file:
            raw = Path(judgment_file).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()
    except OSError as exc:
        return None, f"cannot read judgment: {exc}"

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"judgment is not valid JSON: {exc}"

    if not isinstance(parsed, dict):
        return None, "judgment must be a JSON object, not an array or scalar"

    return parsed, None


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def build_parser(
    parent: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    """Register the 'variance-save' subparser and return it.

    Judgment input is read from ``--judgment-file`` when provided;
    otherwise stdin is consumed.  Exactly one of ``--judgment-file`` or
    piped stdin must supply a JSON object.

    Args:
        parent: The subparsers action from the top-level argument parser.

    Returns:
        The configured variance-save ArgumentParser.
    """
    p = parent.add_parser(
        "variance-save",
        help=(
            "Merge session-audit 1a output with LLM judgment fields "
            "and write a combined variance record."
        ),
    )
    p.add_argument(
        "--session-id",
        dest="session_id",
        required=True,
        help="Claude Code session-id to audit and save variance for.",
    )
    p.add_argument(
        "--judgment-file",
        dest="judgment_file",
        default=None,
        help=(
            "Path to a JSON file containing judgment fields "
            "(variance, not_done, severity).  "
            "When omitted, judgment is read from stdin."
        ),
    )
    p.add_argument(
        "--data-dir",
        dest="data_dir",
        type=Path,
        default=Path.home() / ".claude",
        help=(
            "Root of the Claude data directory used to locate the session "
            "transcript.  The transcript is expected at "
            "<data-dir>/projects/<project>/<session-id>.jsonl.  "
            "Defaults to ~/.claude (the standard Claude Code data root)."
        ),
    )
    p.add_argument(
        "--out",
        dest="out_path",
        type=Path,
        default=None,
        help=(
            "Explicit output path for the combined JSON record.  "
            "When omitted, writes to "
            "<base_dir>/variance/<session-id>.json where base_dir is "
            "resolved via CLAUDE_PROSPECTOR_BASE_DIR > CLAUDE_PLUGIN_DATA "
            "> ~/.claude/claude-prospector."
        ),
    )
    return p


def run(args: argparse.Namespace) -> int:
    """Entry point for the variance-save subcommand.

    Resolves the session transcript, loads judgment from file or stdin,
    combines with 1a audit data, and persists the record.  Prints the
    written path to stdout on success.

    Args:
        args: Parsed CLI namespace.  Expected attributes:
            ``args.session_id`` (str), ``args.judgment_file`` (str or
            None), ``args.data_dir`` (Path or None),
            ``args.out_path`` (Path or None).

    Returns:
        Integer exit code (0 on success, 1 on IO failure, 2 on
        validation failure).
    """
    # Transcript search root: --data-dir (defaults to ~/.claude in parser).
    data_dir: Path = args.data_dir

    # Load and parse the judgment.
    judgment, err = _load_judgment(getattr(args, "judgment_file", None))
    if err:
        print(f"variance-save: {err}", file=sys.stderr)
        return EXIT_IO_FAILURE

    # Validate judgment keys.
    try:
        validate_judgment(judgment)
    except ValueError as exc:
        print(f"variance-save: {exc}", file=sys.stderr)
        return EXIT_VALIDATION_FAILURE

    # Resolve session → transcript → audit → persist.
    # Output root is base_dir() (plugin-data), independent of data_dir.
    try:
        out_path = save_variance_record(
            session_id=args.session_id,
            data_dir=data_dir,
            judgment=judgment,
            out_path=getattr(args, "out_path", None),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"variance-save: {exc}", file=sys.stderr)
        return EXIT_IO_FAILURE
    except OSError as exc:
        print(
            f"variance-save: I/O error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_IO_FAILURE

    print(str(out_path), flush=True)
    return EXIT_OK
