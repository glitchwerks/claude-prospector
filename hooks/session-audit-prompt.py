#!/usr/bin/env python3
"""Stop hook: elicit a structured self-audit block from the agent.

This script is a SPIKE hook — it is NOT registered in hooks/hooks.json.
Activate it locally by adding a Stop hook entry to your user-level
``~/.claude/settings.json`` (see ``docs/spikes/2026-05-19-self-audit-spike.md``
for the exact JSON fragment).

Purpose:
    Forces the main Claude Code agent to emit a ``<self-audit>`` block
    before allowing a session turn to end. The block captures what was
    asked, what was done, what was skipped, and what diverged from the
    stated approach. The hook inspects the most recent assistant message
    in the session transcript JSONL; if the block is absent, it returns a
    ``decision: block`` payload so Claude Code re-prompts the agent.

Stop hook input (stdin JSON):
    transcript_path : str
        Absolute path to the session JSONL file on disk.
    stop_hook_active : bool
        True when a prior hook in the chain already blocked. The
        infinite-loop guard: if this is True, exit 0 immediately without
        blocking again.

Stop hook output (stdout):
    ``{"decision": "block", "reason": "<prompt-text>"}`` when the
    ``<self-audit>`` block is absent from the last assistant message.
    No stdout (or an empty JSON object ``{}``) when the block is present
    or when the hook bails out.

Fail-open policy:
    Any I/O, parse, or runtime error exits 0 (allow the stop). Errors are
    written to stderr for diagnostics. This hook must never disrupt the
    user's session.

Exit codes:
    Always 0. Hook failures must not propagate to the session runner.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

# Import the telemetry helper from hooks/lib/ using the same sys.path idiom
# used by other hooks in this repo.
sys.path.insert(0, str(Path(__file__).parent / "lib"))
from self_audit_telemetry import log_outcome  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex to detect a <self-audit> block (case-insensitive, multiline, DOTALL).
_SELF_AUDIT_PATTERN: re.Pattern[str] = re.compile(
    r"<self-audit>.*?</self-audit>",
    re.IGNORECASE | re.DOTALL,
)

# The block prompt returned to the agent when no self-audit is found.
# Keep this between ~150-250 words: long enough to specify each section,
# short enough that the agent won't compress it.
_AUDIT_PROMPT: str = """\
This session is ending. Before stopping, emit a self-audit block in \
this exact format:

<self-audit>
### Original ask
Verbatim quote of the first user message in this session.

### What was done
List each file changed or created, one line each, with a one-sentence
summary of what changed. If no files were modified (discussion or
lookup turn only), write: no code changes — discussion / lookup turn

### What was NOT done
List any items implied by the original ask that were skipped,
deferred, or left incomplete. If every item was addressed, write:
nothing skipped

### Variance
List any work that went beyond the stated scope, any pivot from the
approach described in the original ask, and any premise shift
discovered mid-task. If none, write: no variance
</self-audit>

Emit ONLY the self-audit block as your next response. Do not narrate \
or summarize outside the wrapper. After the block, the session may end.\
"""

# ---------------------------------------------------------------------------
# Transcript reading
# ---------------------------------------------------------------------------


def _read_stdin() -> dict[str, Any]:
    """Read and parse the Stop hook JSON payload from stdin.

    Returns:
        Parsed payload dict, or an empty dict on any parse failure.
    """
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception as exc:
        sys.stderr.write(f"[session-audit-prompt] failed to parse stdin: {exc}\n")
        return {}


def _extract_last_assistant_text(transcript_path: str) -> Optional[str]:
    """Return the text content of the most recent assistant message.

    Reads the JSONL transcript line by line and collects the last entry
    whose ``role`` is ``"assistant"``. Extracts the text from ``content``
    (which may be a plain string or a list of content blocks).

    Args:
        transcript_path: Absolute path to the session JSONL file.

    Returns:
        The concatenated text of the last assistant message, or None if
        the file is empty, unreadable, or contains no assistant messages.

    Raises:
        Does not raise. All errors are logged to stderr; returns None.
    """
    path = Path(transcript_path)
    if not path.exists():
        sys.stderr.write(
            f"[session-audit-prompt] transcript not found:" f" {transcript_path}\n"
        )
        log_outcome("transcript_missing", transcript_path)
        return None

    last_assistant_text: Optional[str] = None

    try:
        with open(path, encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    sys.stderr.write(
                        f"[session-audit-prompt] skipping malformed line"
                        f" {lineno} in transcript: {exc}\n"
                    )
                    continue

                if not isinstance(event, dict):
                    continue

                role = event.get("role")
                if role != "assistant":
                    continue

                content = event.get("content", "")
                text = _content_to_text(content)
                if text is not None:
                    last_assistant_text = text

    except OSError as exc:
        sys.stderr.write(f"[session-audit-prompt] error reading transcript: {exc}\n")
        log_outcome("transcript_read_error", transcript_path)
        return None

    return last_assistant_text


def _content_to_text(content: Any) -> Optional[str]:
    """Extract plain text from a message content field.

    Handles two formats observed in Claude Code transcript JSONL:
    - A plain string (older format).
    - A list of content blocks, each a dict with ``type`` and ``text``
      keys; only ``{"type": "text", ...}`` blocks are included.

    Args:
        content: The raw value of the ``content`` field in a message.

    Returns:
        Concatenated text, an empty string if the message has no text
        blocks, or None if the content type is unrecognisable.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_val = block.get("text", "")
                if isinstance(text_val, str):
                    parts.append(text_val)
        return "\n".join(parts)

    return None


# ---------------------------------------------------------------------------
# Self-audit detection
# ---------------------------------------------------------------------------


def _has_self_audit(text: str) -> bool:
    """Return True when *text* contains a complete ``<self-audit>`` block.

    The check is case-insensitive and allows the block to span multiple
    lines. Both the opening and closing tags must be present.

    Args:
        text: The assistant message text to inspect.

    Returns:
        True if a ``<self-audit>…</self-audit>`` block is found.
    """
    return bool(_SELF_AUDIT_PATTERN.search(text))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point for the Stop hook.

    Steps:
    1. Read and parse stdin JSON payload.
    2. If ``stop_hook_active`` is True, bail out immediately (loop guard).
    3. Retrieve ``transcript_path`` from the payload.
    4. Read the last assistant message from the transcript.
    5. If the message contains a ``<self-audit>`` block, allow the stop.
    6. If not, emit a ``decision: block`` JSON payload to stdout so Claude
       Code re-prompts the agent with the audit request.

    Returns:
        Always 0 — hook failures must not propagate to the session runner.
    """
    try:
        payload = _read_stdin()

        # Step 2: infinite-loop guard.
        if payload.get("stop_hook_active") is True:
            sys.stderr.write(
                "[session-audit-prompt] stop_hook_active=True —"
                " bailing out to prevent infinite loop\n"
            )
            log_outcome("stop_hook_active")
            return 0

        # Step 3: locate transcript.
        transcript_path = payload.get("transcript_path", "")
        if not transcript_path:
            sys.stderr.write(
                "[session-audit-prompt] transcript_path missing from"
                " payload — allowing stop\n"
            )
            log_outcome("no_transcript_path")
            return 0

        # Step 4: read last assistant message.
        last_text = _extract_last_assistant_text(transcript_path)
        if last_text is None:
            sys.stderr.write(
                "[session-audit-prompt] could not read last assistant"
                " message — allowing stop\n"
            )
            log_outcome("no_assistant_text", transcript_path)
            return 0

        # Step 5: check for existing self-audit block.
        if _has_self_audit(last_text):
            sys.stderr.write(
                "[session-audit-prompt] <self-audit> block found —" " allowing stop\n"
            )
            log_outcome("present", transcript_path)
            return 0

        # Step 6: block and elicit the audit.
        sys.stderr.write(
            "[session-audit-prompt] no <self-audit> block found —" " requesting audit\n"
        )
        log_outcome("blocked", transcript_path)
        decision = json.dumps({"decision": "block", "reason": _AUDIT_PROMPT})
        sys.stdout.write(decision + "\n")

    except Exception as exc:
        sys.stderr.write(f"[session-audit-prompt] unexpected error: {exc}\n")
        log_outcome("unexpected_error")

    return 0


if __name__ == "__main__":
    sys.exit(main())
