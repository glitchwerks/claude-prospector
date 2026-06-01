"""Tests for the session-audit subcommand.

Covers: empty transcript, single-ask session, multi-ask session
(original_ask = first, prior_asks populated), tool-use extraction
(Edit/Write/NotebookEdit paths), malformed/garbage JSONL lines
(skipped gracefully), tool_result user-entries excluded from asks,
and CLI routing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers shared across tests (no fixtures needed for simple JSONL building)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _user_line(
    text: str | list,
    user_type: str = "external",
    session_id: str = "test-session",
) -> dict:
    """Build a minimal user message dict for JSONL fixtures.

    Args:
        text: Message content — either a plain string or a list of
            content blocks (for tool_result entries or multi-block
            messages).
        user_type: The ``userType`` field. Use ``"external"`` for
            real user asks, any other value for internal entries.
        session_id: The session identifier string.

    Returns:
        A dict shaped like a real Claude Code JSONL user entry.
    """
    return {
        "type": "user",
        "userType": user_type,
        "sessionId": session_id,
        "message": {
            "role": "user",
            "content": text,
        },
    }


def _tool_result_user_line(
    tool_use_id: str = "tu-1",
    session_id: str = "test-session",
) -> dict:
    """Build a user entry whose content is a tool_result block.

    These are NOT real user asks and must be excluded from
    original_ask / prior_asks.

    Args:
        tool_use_id: The tool_use_id referenced by the tool_result.
        session_id: The session identifier string.

    Returns:
        A dict shaped like a Claude Code JSONL tool-result user entry.
    """
    return {
        "type": "user",
        "userType": "external",
        "sessionId": session_id,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "tool output here",
                }
            ],
        },
    }


def _assistant_with_tool_use(
    tool_name: str,
    file_path: str,
    session_id: str = "test-session",
) -> dict:
    """Build an assistant message containing a single tool_use block.

    Args:
        tool_name: The tool name (e.g. ``"Edit"``, ``"Write"``).
        file_path: The ``input.file_path`` value for the tool_use.
        session_id: The session identifier string.

    Returns:
        A dict shaped like a real Claude Code JSONL assistant entry.
    """
    return {
        "type": "assistant",
        "sessionId": session_id,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu-1",
                    "name": tool_name,
                    "input": {"file_path": file_path},
                }
            ],
        },
    }


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    """Write a list of dicts as JSONL to *path*.

    Args:
        path: Destination file path.
        lines: Dicts to serialise, one per line.
    """
    path.write_text(
        "\n".join(json.dumps(line) for line in lines),
        encoding="utf-8",
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    """Run claude_prospector as a module and capture raw output bytes.

    Returns raw bytes rather than decoded text so callers control the
    encoding.  Use ``.stdout.decode("utf-8")`` when expecting JSON or
    known-UTF-8 output; avoid decoding help text (which argparse emits
    in the system locale encoding on Windows).

    Args:
        *args: CLI arguments appended after the module name.

    Returns:
        CompletedProcess with stdout/stderr as bytes and returncode.
    """
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", *args],
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Import target — delayed until implementation exists so tests can be
# collected even if the module is missing (they'll fail at the import line
# inside the test body, not at collection time).
# ---------------------------------------------------------------------------


def _import_module():
    """Import the session_audit module, raising ImportError if absent."""
    from claude_prospector.cli import session_audit  # noqa: PLC0415

    return session_audit


# ===========================================================================
# TestSessionAuditImport — module must be importable and export the contract
# ===========================================================================


class TestSessionAuditImport:
    """The session_audit module must exist and export required symbols."""

    def test_module_importable(self) -> None:
        """session_audit module must be importable from cli package."""
        mod = _import_module()
        assert mod is not None

    def test_build_parser_callable(self) -> None:
        """session_audit must export a build_parser callable."""
        mod = _import_module()
        assert callable(mod.build_parser)

    def test_run_callable(self) -> None:
        """session_audit must export a run callable."""
        mod = _import_module()
        assert callable(mod.run)

    def test_audit_session_callable(self) -> None:
        """session_audit must export an audit_session pure function."""
        mod = _import_module()
        assert callable(mod.audit_session)


# ===========================================================================
# TestAuditSession — pure function over in-memory entries
# ===========================================================================


class TestAuditSession:
    """Unit tests for audit_session() — no I/O, synthetic entry lists."""

    def test_empty_transcript_returns_none_original_ask(self) -> None:
        """An empty entry list yields original_ask = None."""
        mod = _import_module()
        result = mod.audit_session([])
        assert result["original_ask"] is None

    def test_empty_transcript_prior_asks_empty(self) -> None:
        """An empty entry list yields prior_asks = []."""
        mod = _import_module()
        result = mod.audit_session([])
        assert result["prior_asks"] == []

    def test_empty_transcript_actions_empty(self) -> None:
        """An empty entry list yields actions = []."""
        mod = _import_module()
        result = mod.audit_session([])
        assert result["actions"] == []

    def test_single_ask_sets_original_ask(self) -> None:
        """A session with one user message sets original_ask to its text."""
        mod = _import_module()
        entries = [
            _user_line("Please add a --dry-run flag to the CLI."),
        ]
        result = mod.audit_session(entries)
        assert result["original_ask"] == "Please add a --dry-run flag to the CLI."

    def test_single_ask_prior_asks_empty(self) -> None:
        """A session with one user message leaves prior_asks empty."""
        mod = _import_module()
        entries = [
            _user_line("Please add a --dry-run flag to the CLI."),
        ]
        result = mod.audit_session(entries)
        assert result["prior_asks"] == []

    def test_multi_ask_first_is_original(self) -> None:
        """With multiple user asks original_ask is the FIRST, not the last.

        This is the core regression case: the 696584a5 session started
        "Add a --dry-run flag…" but a last-message recall bug would have
        returned the final message ("close the pr") as the original ask.
        """
        mod = _import_module()
        entries = [
            _user_line("Add a --dry-run flag to the CLI."),
            _user_line("Now also write tests for it."),
            _user_line("close the pr"),
        ]
        result = mod.audit_session(entries)
        assert result["original_ask"] == "Add a --dry-run flag to the CLI."

    def test_multi_ask_subsequent_in_prior_asks(self) -> None:
        """Subsequent user asks must appear in prior_asks in order."""
        mod = _import_module()
        entries = [
            _user_line("Add a --dry-run flag to the CLI."),
            _user_line("Now also write tests for it."),
            _user_line("close the pr"),
        ]
        result = mod.audit_session(entries)
        assert result["prior_asks"] == [
            "Now also write tests for it.",
            "close the pr",
        ]

    def test_tool_result_user_entries_excluded_from_original_ask(self) -> None:
        """tool_result user entries must NOT be treated as user asks.

        A user entry whose content is a list of tool_result blocks is
        an API artifact, not a real user message.
        """
        mod = _import_module()
        entries = [
            _tool_result_user_line("tu-1"),
            _user_line("This is the real ask."),
        ]
        result = mod.audit_session(entries)
        assert result["original_ask"] == "This is the real ask."

    def test_tool_result_user_entries_excluded_from_prior_asks(self) -> None:
        """tool_result entries interspersed between asks must not appear
        in prior_asks."""
        mod = _import_module()
        entries = [
            _user_line("First ask."),
            _tool_result_user_line("tu-1"),
            _user_line("Second real ask."),
        ]
        result = mod.audit_session(entries)
        assert result["prior_asks"] == ["Second real ask."]

    def test_edit_tool_use_captured_in_actions(self) -> None:
        """Edit tool_use events must appear in actions with file_path."""
        mod = _import_module()
        entries = [
            _user_line("Fix the bug."),
            _assistant_with_tool_use("Edit", "src/foo.py"),
        ]
        result = mod.audit_session(entries)
        assert len(result["actions"]) == 1
        assert result["actions"][0]["file_path"] == "src/foo.py"
        assert result["actions"][0]["tool"] == "Edit"

    def test_write_tool_use_captured_in_actions(self) -> None:
        """Write tool_use events must appear in actions with file_path."""
        mod = _import_module()
        entries = [
            _user_line("Create the module."),
            _assistant_with_tool_use("Write", "src/new_module.py"),
        ]
        result = mod.audit_session(entries)
        assert len(result["actions"]) == 1
        assert result["actions"][0]["file_path"] == "src/new_module.py"
        assert result["actions"][0]["tool"] == "Write"

    def test_notebook_edit_tool_use_captured_in_actions(self) -> None:
        """NotebookEdit tool_use events must appear in actions with file_path."""
        mod = _import_module()
        entries = [
            _user_line("Edit the notebook."),
            _assistant_with_tool_use("NotebookEdit", "analysis.ipynb"),
        ]
        result = mod.audit_session(entries)
        assert len(result["actions"]) == 1
        assert result["actions"][0]["file_path"] == "analysis.ipynb"
        assert result["actions"][0]["tool"] == "NotebookEdit"

    def test_bash_tool_use_not_in_actions(self) -> None:
        """Bash tool_use events must NOT appear in the actions list.

        Bash invocations are out of scope for session-audit 1a per the
        design spec.
        """
        mod = _import_module()
        entries = [
            _user_line("Run the tests."),
            {
                "type": "assistant",
                "sessionId": "test-session",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu-2",
                            "name": "Bash",
                            "input": {"command": "pytest"},
                        }
                    ],
                },
            },
        ]
        result = mod.audit_session(entries)
        assert result["actions"] == []

    def test_multiple_edit_tools_all_captured(self) -> None:
        """Multiple edit tool_use events across assistant entries are all
        captured in order."""
        mod = _import_module()
        entries = [
            _user_line("Refactor everything."),
            _assistant_with_tool_use("Edit", "src/a.py"),
            _assistant_with_tool_use("Write", "src/b.py"),
            _assistant_with_tool_use("NotebookEdit", "notebooks/c.ipynb"),
        ]
        result = mod.audit_session(entries)
        assert len(result["actions"]) == 3
        assert result["actions"][0]["file_path"] == "src/a.py"
        assert result["actions"][1]["file_path"] == "src/b.py"
        assert result["actions"][2]["file_path"] == "notebooks/c.ipynb"

    def test_content_block_list_extracts_text(self) -> None:
        """User messages with list content blocks have text extracted."""
        mod = _import_module()
        entries = [
            _user_line([{"type": "text", "text": "Ask from content block."}]),
        ]
        result = mod.audit_session(entries)
        assert result["original_ask"] == "Ask from content block."

    def test_only_tool_results_no_real_asks(self) -> None:
        """A transcript with only tool_result user entries has no original_ask."""
        mod = _import_module()
        entries = [
            _tool_result_user_line("tu-1"),
            _tool_result_user_line("tu-2"),
        ]
        result = mod.audit_session(entries)
        assert result["original_ask"] is None
        assert result["prior_asks"] == []

    def test_result_schema_keys_present(self) -> None:
        """audit_session result must contain the required schema keys."""
        mod = _import_module()
        result = mod.audit_session([])
        required_keys = {"original_ask", "prior_asks", "actions"}
        assert required_keys.issubset(result.keys())

    def test_no_duplicate_asks_adjacent_equal_messages(self) -> None:
        """Identical adjacent user messages both appear (no deduplication).

        The spec says 'distinct' in the sense of subsequent, not unique
        — identical repeated asks are each genuine asks.
        """
        mod = _import_module()
        entries = [
            _user_line("Run it again."),
            _user_line("Run it again."),
        ]
        result = mod.audit_session(entries)
        assert result["original_ask"] == "Run it again."
        assert result["prior_asks"] == ["Run it again."]


# ===========================================================================
# TestReadTranscriptGraceful — I/O edge cases (malformed JSONL)
# ===========================================================================


class TestReadTranscriptGraceful:
    """Malformed and edge-case JSONL lines must be skipped gracefully."""

    def test_malformed_lines_skipped_gracefully(self, tmp_path: Path) -> None:
        """Garbage JSONL lines must be skipped; valid lines must be parsed.

        A file with 1 valid user-ask line and 2 garbage lines must
        still yield original_ask from the valid line.
        """
        mod = _import_module()
        f = tmp_path / "test.jsonl"
        valid = json.dumps(_user_line("The real ask."))
        f.write_text(
            "\n".join(
                [
                    "NOT JSON AT ALL }{",
                    valid,
                    "also garbage",
                ]
            ),
            encoding="utf-8",
        )
        entries, _count = mod.read_transcript(f)
        result = mod.audit_session(entries)
        assert result["original_ask"] == "The real ask."

    def test_empty_file_returns_empty_entries(self, tmp_path: Path) -> None:
        """An empty JSONL file yields zero entries and zero non-blank lines."""
        mod = _import_module()
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        entries, non_blank = mod.read_transcript(f)
        assert entries == []
        assert non_blank == 0

    def test_blank_lines_only_skipped(self, tmp_path: Path) -> None:
        """A file with only blank lines yields zero entries."""
        mod = _import_module()
        f = tmp_path / "blanks.jsonl"
        f.write_text("\n\n\n", encoding="utf-8")
        entries, non_blank = mod.read_transcript(f)
        assert entries == []
        assert non_blank == 0

    def test_all_garbage_nonzero_non_blank_count(self, tmp_path: Path) -> None:
        """A file with only unparseable lines has non_blank_lines > 0."""
        mod = _import_module()
        f = tmp_path / "garbage.jsonl"
        f.write_text("}{garbage\nalso garbage\n", encoding="utf-8")
        entries, non_blank = mod.read_transcript(f)
        assert entries == []
        assert non_blank == 2


# ===========================================================================
# TestOutputFormats — render_json and render_text
# ===========================================================================


class TestOutputFormats:
    """Output rendering must produce valid JSON or human-readable text."""

    def test_render_json_is_valid_json(self) -> None:
        """render_json must produce a parseable JSON string."""
        mod = _import_module()
        result = mod.audit_session([_user_line("Fix the bug.")])
        output = mod.render_json(result)
        parsed = json.loads(output)
        assert "original_ask" in parsed

    def test_render_json_schema_structure(self) -> None:
        """render_json output must match the documented schema shape."""
        mod = _import_module()
        result = mod.audit_session(
            [
                _user_line("First ask."),
                _user_line("Second ask."),
                _assistant_with_tool_use("Edit", "src/foo.py"),
            ]
        )
        parsed = json.loads(mod.render_json(result))
        assert parsed["original_ask"] == "First ask."
        assert parsed["prior_asks"] == ["Second ask."]
        assert len(parsed["actions"]) == 1
        assert parsed["actions"][0]["tool"] == "Edit"
        assert parsed["actions"][0]["file_path"] == "src/foo.py"

    def test_render_text_contains_original_ask(self) -> None:
        """render_text output must contain the original_ask text."""
        mod = _import_module()
        result = mod.audit_session([_user_line("Do the thing.")])
        output = mod.render_text(result)
        assert "Do the thing." in output

    def test_render_text_contains_section_headers(self) -> None:
        """render_text must include labelled sections."""
        mod = _import_module()
        result = mod.audit_session(
            [
                _user_line("Fix it."),
                _assistant_with_tool_use("Write", "out.py"),
            ]
        )
        output = mod.render_text(result)
        # Must include labelled headers
        assert "Original ask" in output or "original_ask" in output.lower()
        assert "Actions" in output or "actions" in output.lower()


# ===========================================================================
# TestCLIRouting — subprocess integration
# ===========================================================================


class TestCLIRouting:
    """session-audit subcommand must be wired into the CLI entry point."""

    def test_session_audit_in_help_output(self) -> None:
        """'python -m claude_prospector' help must list 'session-audit'."""
        result = _run_cli()
        # Decode with errors="replace" — help text may contain locale chars.
        combined = result.stdout.decode(
            "utf-8", errors="replace"
        ) + result.stderr.decode("utf-8", errors="replace")
        assert "session-audit" in combined

    def test_session_audit_help_exits_0(self) -> None:
        """'session-audit --help' must exit 0."""
        result = _run_cli("session-audit", "--help")
        assert result.returncode == 0

    def test_session_audit_missing_file_exits_nonzero(self, tmp_path: Path) -> None:
        """Passing a nonexistent --path must exit non-zero."""
        missing = str(tmp_path / "nonexistent.jsonl")
        result = _run_cli("session-audit", "--path", missing)
        assert result.returncode != 0

    def test_session_audit_valid_file_exits_0(self, tmp_path: Path) -> None:
        """A valid single-ask transcript must exit 0 and emit JSON."""
        f = tmp_path / "session.jsonl"
        _write_jsonl(f, [_user_line("Do the thing.")])
        result = _run_cli("session-audit", "--path", str(f))
        assert result.returncode == 0
        parsed = json.loads(result.stdout.decode("utf-8"))
        assert parsed["original_ask"] == "Do the thing."

    def test_session_audit_format_text_exits_0(self, tmp_path: Path) -> None:
        """'session-audit --format text' must exit 0."""
        f = tmp_path / "session.jsonl"
        _write_jsonl(f, [_user_line("Do the thing.")])
        result = _run_cli("session-audit", "--path", str(f), "--format", "text")
        assert result.returncode == 0
        assert "Do the thing." in result.stdout.decode("utf-8")

    def test_session_audit_empty_transcript_exits_nonzero(self, tmp_path: Path) -> None:
        """An empty transcript (no user turns) must exit non-zero."""
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        result = _run_cli("session-audit", "--path", str(f))
        assert result.returncode != 0
