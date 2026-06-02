"""Session-audit subcommand: extract ask vs. action data from a transcript.

Walks a Claude Code transcript JSONL once and emits structured JSON (or
human-readable text) capturing what was asked and what file edits were
made, at **zero LLM cost** — purely deterministic extraction.

JSON schema (``--format json``, the default)::

    {
        "original_ask": "<string or null>",
        "prior_asks":   ["<string>", ...],
        "actions":      [
            {"tool": "<Edit|Write|NotebookEdit>", "file_path": "<string>"},
            ...
        ]
    }

Fields:
    original_ask:
        Verbatim text of the first non-system, non-tool-result external
        user message.  ``null`` when the transcript has no qualifying
        user turn.
    prior_asks:
        Verbatim text of each *subsequent* distinct external user message,
        in transcript order.  Empty array for single-ask sessions.
    actions:
        Chronologically ordered list of ``Edit``/``Write``/``NotebookEdit``
        tool_use events, each with the target ``file_path`` and the
        ``tool`` name.  Bash invocations are excluded (out of scope).

Exit codes:
    0  Success — output written to stdout.
    1  IO failure — file missing, unreadable, or other OSError.
    2  No user turns — transcript has no external user entries.
    3  Not JSONL — file has non-blank content but every line fails
       json.loads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Re-use the shared read_transcript and text-extraction helper so we
# don't maintain a divergent copy of the same JSONL parsing logic.
from claude_prospector.cli.session_summary import (
    _EDIT_TOOLS,
    _extract_text_from_content,
    read_transcript,
)

EXIT_OK = 0
EXIT_IO_FAILURE = 1
EXIT_NO_USER_TURNS = 2
EXIT_NOT_JSONL = 3

# ---------------------------------------------------------------------------
# Type alias for the audit result dict (avoids a heavy TypedDict dependency
# while keeping the return type explicit in docstrings).
# ---------------------------------------------------------------------------

AuditResult = dict[str, Any]


# ---------------------------------------------------------------------------
# Session-id → path resolver (shared with variance_save)
# ---------------------------------------------------------------------------


def resolve_session_id_to_path(
    session_id: str,
    data_dir: Path,
) -> Path:
    """Resolve a session-id to its transcript JSONL path.

    Walks ``data_dir/projects/**/<session_id>.jsonl`` (one glob level
    deep into project directories) and returns the single matching path.

    Args:
        session_id: The Claude Code session identifier (filename stem).
        data_dir: Root of the Claude data directory (e.g. ``~/.claude``).
            The search walks ``<data_dir>/projects/``; if that
            subdirectory does not exist, zero matches are returned.

    Returns:
        The resolved ``Path`` to the transcript JSONL file.

    Raises:
        FileNotFoundError: When no matching transcript is found.
        ValueError: When more than one transcript matches the session-id.
    """
    projects_dir = data_dir / "projects"
    if not projects_dir.is_dir():
        raise FileNotFoundError(
            f"session-id '{session_id}' not found: "
            f"projects directory '{projects_dir}' does not exist."
        )

    matches = list(projects_dir.glob(f"*/{session_id}.jsonl"))

    if len(matches) == 0:
        raise FileNotFoundError(
            f"session-id '{session_id}' not found under '{projects_dir}'."
        )
    if len(matches) > 1:
        paths_str = ", ".join(str(m) for m in sorted(matches))
        raise ValueError(
            f"session-id '{session_id}' is ambiguous — "
            f"found {len(matches)} transcripts: {paths_str}"
        )

    return matches[0]


# ---------------------------------------------------------------------------
# Core extraction — pure function, no I/O
# ---------------------------------------------------------------------------


def _is_tool_result_entry(entry: dict) -> bool:
    """Return True when a user entry carries only tool_result content.

    Tool-result entries are API artifacts that deliver tool output back
    to the model.  They look like user turns but are NOT genuine user
    asks and must be excluded from ``original_ask`` / ``prior_asks``.

    A user entry is classified as a tool_result entry when its
    ``message.content`` is a list whose every non-empty block has
    ``type == "tool_result"``.

    Args:
        entry: A parsed JSONL entry dict.

    Returns:
        ``True`` when the entry carries only tool_result content blocks.
    """
    msg = entry.get("message", {})
    content = msg.get("content", "")
    if not isinstance(content, list):
        return False
    # At least one block must be present, and every block with a
    # recognisable type must be "tool_result".
    tool_result_blocks = [
        b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    other_typed_blocks = [
        b
        for b in content
        if isinstance(b, dict)
        and b.get("type") is not None
        and b.get("type") != "tool_result"
    ]
    return len(tool_result_blocks) > 0 and len(other_typed_blocks) == 0


def _is_real_user_ask(entry: dict) -> bool:
    """Return True when *entry* represents a genuine external user ask.

    A genuine ask is:
    - ``type == "user"`` AND ``userType == "external"``
    - NOT a tool_result entry (see :func:`_is_tool_result_entry`)

    Args:
        entry: A parsed JSONL entry dict.

    Returns:
        ``True`` for genuine user asks.
    """
    if not (entry.get("type") == "user" and entry.get("userType") == "external"):
        return False
    return not _is_tool_result_entry(entry)


def _extract_ask_text(entry: dict) -> str:
    """Extract the verbatim text from a user ask entry.

    Args:
        entry: A genuine user ask entry (pre-validated by
            :func:`_is_real_user_ask`).

    Returns:
        The extracted text string (may be empty if the content is
        structurally unusual).
    """
    msg = entry.get("message", {})
    content = msg.get("content", "")
    return _extract_text_from_content(content).strip()


def _collect_edit_actions(entries: list[dict]) -> list[dict[str, str]]:
    """Collect all Edit/Write/NotebookEdit tool_use events from entries.

    Iterates assistant entries in file order, extracts tool_use blocks
    whose ``name`` is in ``_EDIT_TOOLS``, and returns them as a list
    of ``{"tool": "<name>", "file_path": "<path>"}`` dicts.

    Args:
        entries: Parsed JSONL entries in file order.

    Returns:
        Chronologically ordered list of action dicts.
    """
    actions: list[dict[str, str]] = []
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            name: str = block.get("name", "")
            if name not in _EDIT_TOOLS:
                continue
            inp: dict = block.get("input", {})
            file_path: str = inp.get("file_path", "")
            actions.append({"tool": name, "file_path": file_path})
    return actions


def audit_session(entries: list[dict]) -> AuditResult:
    """Derive ask-vs-action audit data from already-parsed transcript entries.

    Pure function — no I/O.  The caller is responsible for reading and
    parsing the JSONL file; this function only classifies and extracts.

    Algorithm:
        1. Walk entries in order collecting genuine user asks (filtering
           out tool_result entries).
        2. ``original_ask`` = text of the first genuine ask (or ``None``
           when absent).
        3. ``prior_asks`` = texts of all subsequent genuine asks in order.
        4. ``actions`` = all Edit/Write/NotebookEdit tool_use events.

    Args:
        entries: Parsed JSONL entry dicts in file order.  May be empty.

    Returns:
        An :data:`AuditResult` dict with keys ``original_ask`` (``str``
        or ``None``), ``prior_asks`` (``list[str]``), and ``actions``
        (``list[dict[str, str]]``).
    """
    ask_texts: list[str] = []
    for entry in entries:
        if _is_real_user_ask(entry):
            text = _extract_ask_text(entry)
            ask_texts.append(text)

    original_ask: str | None = ask_texts[0] if ask_texts else None
    prior_asks: list[str] = ask_texts[1:] if len(ask_texts) > 1 else []
    actions = _collect_edit_actions(entries)

    return {
        "original_ask": original_ask,
        "prior_asks": prior_asks,
        "actions": actions,
    }


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def render_json(result: AuditResult) -> str:
    """Render an audit result as a pretty-printed JSON string.

    Uses ``indent=2`` and ``ensure_ascii=False`` for consistency with
    the ``session-summary`` subcommand.  Does **not** append a trailing
    newline — the caller (``run``) adds exactly one.

    Args:
        result: The audit result dict from :func:`audit_session`.

    Returns:
        A JSON string without a trailing newline.
    """
    return json.dumps(result, indent=2, ensure_ascii=False)


def render_text(result: AuditResult) -> str:
    """Render an audit result as a human-readable text summary.

    Intended for ``--format text``.  Output template::

        Original ask: <text or "(none)">

        Prior asks:
          - <ask 1>
          ...

        Actions (Edit/Write/NotebookEdit):
          - <tool>: <file_path>
          ...

    Does **not** append a trailing newline — the caller (``run``) adds
    exactly one.

    Args:
        result: The audit result dict from :func:`audit_session`.

    Returns:
        Multi-line string without a trailing newline.
    """
    original = result.get("original_ask") or "(none)"
    prior = result.get("prior_asks", [])
    actions = result.get("actions", [])

    lines = [f"Original ask: {original}", ""]
    if prior:
        lines.append("Prior asks:")
        for ask in prior:
            lines.append(f"  - {ask}")
    else:
        lines.append("Prior asks: (none)")
    lines.append("")
    lines.append("Actions (Edit/Write/NotebookEdit):")
    if actions:
        for action in actions:
            tool = action.get("tool", "?")
            fp = action.get("file_path", "?")
            lines.append(f"  - {tool}: {fp}")
    else:
        lines.append("  (none)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def build_parser(
    parent: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    """Register the 'session-audit' subparser and return it.

    Accepts either ``--path <transcript.jsonl>`` or
    ``--session-id <id>``; exactly one is required.  When
    ``--session-id`` is used, ``--data-dir`` controls the root of the
    search (defaults to ``~/.claude``).

    Args:
        parent: The subparsers action from the top-level argument parser.

    Returns:
        The configured session-audit ArgumentParser.
    """
    p = parent.add_parser(
        "session-audit",
        help=(
            "Extract ask-vs-action audit data from a Claude Code "
            "transcript at zero LLM cost."
        ),
    )

    # Mutually exclusive group: exactly one of --path or --session-id.
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--path",
        help="Path to the transcript JSONL file.",
    )
    group.add_argument(
        "--session-id",
        dest="session_id",
        help=(
            "Claude Code session-id.  Resolved to a transcript by "
            "walking <data-dir>/projects/**/<id>.jsonl."
        ),
    )

    p.add_argument(
        "--data-dir",
        dest="data_dir",
        type=Path,
        default=Path.home() / ".claude",
        help=(
            "Root of the Claude data directory used when resolving "
            "--session-id (default: ~/.claude)."
        ),
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "text"],
        default="json",
        help="Output format: 'json' (default) or 'text' (human-readable).",
    )
    p.add_argument(
        "--batch",
        action="store_true",
        default=False,
        help=(
            "Walk ~/.claude/projects/**/*.jsonl and emit an array of "
            "per-session audits.  (Not yet implemented — exits with a "
            "clear NotImplementedError message.)"
        ),
    )
    return p


def run(args: argparse.Namespace) -> int:
    """Entry point for the session-audit subcommand.

    Dispatches ``--path`` or ``--session-id`` through the full parse →
    audit → render pipeline, printing JSON (or text) to stdout on
    success and a diagnostic line to stderr on failure.

    When ``--session-id`` is supplied, the id is resolved to a
    transcript path by walking ``<args.data_dir>/projects/``.

    Args:
        args: Parsed CLI namespace.  Expected attributes:
            ``args.path`` (str or None), ``args.session_id`` (str or
            None), ``args.data_dir`` (Path), ``args.output_format``
            (str), ``args.batch`` (bool).

    Returns:
        Integer exit code (one of ``EXIT_OK``, ``EXIT_IO_FAILURE``,
        ``EXIT_NO_USER_TURNS``, ``EXIT_NOT_JSONL``).
    """
    # --batch is stubbed pending clean implementation (issue #162 notes).
    if getattr(args, "batch", False):
        print(
            "session-audit: --batch is not yet implemented",
            file=sys.stderr,
        )
        return EXIT_IO_FAILURE

    # Resolve transcript path from --path or --session-id.
    if getattr(args, "session_id", None):
        data_dir: Path = getattr(args, "data_dir", Path.home() / ".claude")
        try:
            path = resolve_session_id_to_path(args.session_id, data_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(
                f"session-audit: {exc}",
                file=sys.stderr,
            )
            return EXIT_IO_FAILURE
    else:
        path = Path(args.path)

    # ── IO failure ──────────────────────────────────────────────────────
    try:
        entries, non_blank_lines = read_transcript(path)
    except OSError as exc:
        print(
            f"session-audit: cannot read transcript at '{path}': "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_IO_FAILURE

    # ── Not JSONL ───────────────────────────────────────────────────────
    if not entries and non_blank_lines > 0:
        print(
            f"session-audit: transcript '{path}' is not valid JSONL",
            file=sys.stderr,
        )
        return EXIT_NOT_JSONL

    # ── No user turns ───────────────────────────────────────────────────
    has_user_turns = any(_is_real_user_ask(e) for e in entries)
    if not has_user_turns:
        print(
            f"session-audit: transcript '{path}' contains no user turns",
            file=sys.stderr,
        )
        return EXIT_NO_USER_TURNS

    # ── Success path ────────────────────────────────────────────────────
    skipped = non_blank_lines - len(entries)
    if skipped > 0:
        print(
            f"session-audit: skipped {skipped} malformed line(s) in " f"'{path}'",
            file=sys.stderr,
        )

    result = audit_session(entries)

    if args.output_format == "json":
        output = render_json(result)
    else:
        output = render_text(result)

    print(output, flush=True)
    return EXIT_OK
