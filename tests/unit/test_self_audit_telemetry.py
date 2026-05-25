"""Unit tests for hooks/lib/self_audit_telemetry.py.

Tests are written against the public ``log_outcome`` function. Each test
covers a single behavior and is designed to fail before the module exists
(TDD red phase).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Import the module under test via sys.path manipulation, matching the idiom
# used by the hooks themselves.
# ---------------------------------------------------------------------------

HOOKS_LIB = Path(__file__).parent.parent.parent / "hooks" / "lib"
sys.path.insert(0, str(HOOKS_LIB))

import self_audit_telemetry  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _read_jsonl(path: Path) -> list[dict]:
    """Return parsed JSON objects from a JSONL file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLogOutcomeWritesEntry:
    """log_outcome writes a well-formed JSONL entry."""

    def test_log_outcome_writes_jsonl_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single call produces one JSONL line with correct fields."""
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))

        self_audit_telemetry.log_outcome("blocked", "/foo/bar/abc-123.jsonl")

        log_file = tmp_path / "session-audit.jsonl"
        assert log_file.exists(), "JSONL file was not created"

        entries = _read_jsonl(log_file)
        assert len(entries) == 1, "Expected exactly one JSONL entry"

        entry = entries[0]
        assert entry["state"] == "blocked"
        assert entry["session_id"] == "abc-123"
        assert _TIMESTAMP_RE.match(
            entry["timestamp"]
        ), f"timestamp {entry['timestamp']!r} does not match ISO-8601 Z format"

    def test_log_outcome_appends(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two calls produce two JSONL lines (append, not overwrite)."""
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))

        self_audit_telemetry.log_outcome("present", "/x/s1.jsonl")
        self_audit_telemetry.log_outcome("blocked", "/x/s2.jsonl")

        log_file = tmp_path / "session-audit.jsonl"
        entries = _read_jsonl(log_file)
        assert len(entries) == 2, "Expected two JSONL entries after two calls"
        assert entries[0]["state"] == "present"
        assert entries[1]["state"] == "blocked"

    def test_log_outcome_creates_parent_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """log_outcome creates missing parent directories."""
        nested = tmp_path / "nonexistent" / "subdir"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(nested))
        assert not nested.exists(), "Precondition: dir must not exist yet"

        self_audit_telemetry.log_outcome("no_transcript_path")

        assert (nested / "session-audit.jsonl").exists()

    def test_log_outcome_empty_transcript_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty transcript_path yields session_id = None in the entry."""
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))

        self_audit_telemetry.log_outcome("present", "")

        log_file = tmp_path / "session-audit.jsonl"
        entries = _read_jsonl(log_file)
        assert len(entries) == 1
        assert entries[0]["session_id"] is None

    def test_log_outcome_swallows_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A broken open() must not raise — telemetry is fail-open."""
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", "/this/path/does/not/exist")

        # Monkeypatch open to raise unconditionally so we exercise the
        # try/except inside log_outcome.
        original_open = open

        def _raise_always(*args, **kwargs):
            # Allow reads (e.g. from pytest internals) but block writes.
            if args and len(args) >= 2 and "a" in str(args[1]):
                raise OSError("simulated write failure")
            return original_open(*args, **kwargs)

        with patch("builtins.open", side_effect=_raise_always):
            # Must not raise.
            self_audit_telemetry.log_outcome("present")
