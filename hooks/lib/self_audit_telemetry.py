"""Structured JSONL telemetry for the self-audit Stop hook.

Appends one JSON line per hook invocation to
``${CLAUDE_PLUGIN_DATA}/session-audit.jsonl``. The log persists across
sessions so it can be queried with ``wc -l``, ``jq``, or Python after
the fact.

Fail-open contract: this module must never raise. Any write failure is
silently swallowed. A broken telemetry write must not break the hook's
fail-open contract.

Public API:
    log_outcome(state, transcript_path="") -> None
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Valid state identifiers (for documentation — not enforced at runtime).
VALID_STATES: tuple[str, ...] = (
    "stop_hook_active",
    "no_transcript_path",
    "transcript_missing",
    "transcript_read_error",
    "no_assistant_text",
    "present",
    "blocked",
    "unexpected_error",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_log_path() -> Path:
    """Return the absolute path to the JSONL telemetry log file.

    Resolves ``${CLAUDE_PLUGIN_DATA}/session-audit.jsonl``. Falls back to
    ``~/.claude/session-audit.jsonl`` when the env var is absent.

    Returns:
        Absolute path to the log file. Not created by this call.
    """
    base = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if base:
        return Path(base) / "session-audit.jsonl"
    return Path.home() / ".claude" / "session-audit.jsonl"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_outcome(state: str, transcript_path: str = "") -> None:
    """Append a structured telemetry line to the self-audit log.

    Writes one JSON object per call to
    ``${CLAUDE_PLUGIN_DATA}/session-audit.jsonl``, creating the file and
    parent dirs if missing. Fields:

        timestamp:   UTC ISO-8601 with 'Z' suffix, no microseconds.
        state:       One of the eight defined states.
        session_id:  ``Path(transcript_path).stem`` if *transcript_path*
                     is non-empty, else ``None``.

    Telemetry MUST never raise — the entire body is wrapped in
    ``try/except`` and swallows all exceptions. A broken telemetry write
    must not break the hook's fail-open contract.

    Args:
        state: One of ``"stop_hook_active"``, ``"no_transcript_path"``,
            ``"transcript_missing"``, ``"transcript_read_error"``,
            ``"no_assistant_text"``, ``"present"``, ``"blocked"``,
            ``"unexpected_error"``.
        transcript_path: Original Stop-hook ``transcript_path`` payload
            value, used to derive ``session_id``. Pass an empty string
            (or omit) when unavailable.
    """
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_id = Path(transcript_path).stem if transcript_path else None
        entry = {
            "timestamp": timestamp,
            "state": state,
            "session_id": session_id,
        }

        log_path = _get_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    except Exception:  # noqa: BLE001
        # Silently swallow — telemetry must never disrupt the hook.
        pass
