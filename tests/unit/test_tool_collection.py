"""Tests for tool-call and MCP-availability collection.

Covers:
- collect_tool_uses: parallel tool_use blocks sharing one message.id are
  both counted (fragment-line hazard regression), repeated tool_use_id
  dedup, tool_result entries on user-type lines excluded, repeated
  identical calls are not collapsed, unreadable file yields no records,
  agent attribution carried through onto each ToolUseRecord.
- collect_availability: signal-absent baseline, builtin-only deltas still
  count as a signal without producing server_sources, MCP-shaped names
  resolve to server names, removed names net out in file order, and
  deferred_tools_delta / mcp_instructions_delta union together.
- collect_tool_uses / collect_unit result-size tracking (issue #262, D-1=M4,
  D-4=yes-isolated-with-secondary-flag): opt-in via the new
  ``track_mcp_call_sizes`` keyword. Covers missing-result -> None (not 0),
  string vs. list ``tool_result.content`` shapes, image blocks excluded
  (rendered ``None``/unknown, never a small non-zero number), duplicate
  ``tool_use_id`` not double-counted, a ``tool_result`` never creating a
  new ``ToolUseRecord``, an orphan ``tool_result`` (no matching tool_use)
  creating no record, and the privacy-gating default: omitting the flag
  leaves every record's ``result_chars`` at ``None`` even when a real,
  sizeable ``tool_result`` is present in the file.
- collect_session / collect_per_session result-size threading (issue #262
  Phase 3 wiring): pins the new keyword-only ``track_mcp_call_sizes``
  parameter on both functions (neither has one before this phase), and
  proves it actually reaches ``collect_unit`` rather than being accepted
  and silently dropped -- exercised via an image-block result (True vs.
  False must differ), not only a plain string result.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_prospector.models import SessionRecord
from claude_prospector.tool_collection import (
    collect_availability,
    collect_per_session,
    collect_session,
    collect_tool_uses,
    collect_unit,
)
from claude_prospector.transcript_walker import AgentTranscript

# ---------------------------------------------------------------------------
# Local fixture builders (this repo's convention: each test file defines its
# own JSONL builders rather than importing from conftest.py).
# ---------------------------------------------------------------------------


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


def _tool_use_line(
    session_id: str,
    message_id: str,
    tool_use_id: str,
    tool_name: str,
    uuid: str,
    timestamp: str,
) -> dict:
    """Build an assistant JSONL entry carrying a single tool_use block.

    Mirrors the real transcript shape: one content block per line, with
    parallel tool calls written as consecutive lines that share a
    ``message.id`` but carry distinct ``tool_use`` ids.

    Args:
        session_id: The session identifier.
        message_id: The assistant message id (``msg_...``). Repeat across
            lines to simulate a multi-block message.
        tool_use_id: The tool-use block id (``toolu_...``).
        tool_name: Raw tool name, e.g. ``"Read"`` or ``"mcp__azure__storage"``.
        uuid: Entry UUID.
        timestamp: ISO 8601 timestamp string.

    Returns:
        A dict shaped like a real Claude Code JSONL assistant entry.
    """
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": session_id,
        "uuid": uuid,
        "message": {
            "id": message_id,
            "model": "claude-opus-4-6",
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": {},
                }
            ],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }


def _availability_line(
    attachment_type: str,
    added: list[str],
    removed: list[str],
    uuid: str,
    timestamp: str,
) -> dict:
    """Build an attachment JSONL entry carrying a tool/server availability delta.

    Args:
        attachment_type: ``"deferred_tools_delta"`` or
            ``"mcp_instructions_delta"``.
        added: Names added by this delta.
        removed: Names removed by this delta.
        uuid: Entry UUID.
        timestamp: ISO 8601 timestamp string.

    Returns:
        A dict shaped like a real Claude Code JSONL attachment entry.
    """
    return {
        "type": "attachment",
        "timestamp": timestamp,
        "uuid": uuid,
        "attachment": {
            "type": attachment_type,
            "addedNames": added,
            "removedNames": removed,
        },
    }


def _user_result_line(
    tool_use_id: str,
    content: str | list[dict],
    uuid: str,
    timestamp: str,
) -> dict:
    """Build a user JSONL entry carrying a single tool_result block.

    Args:
        tool_use_id: The id of the tool_use this result answers.
        content: Either a plain string or a list of content blocks (the
            two shapes observed in real transcripts, per the plan's §1
            structural probe).
        uuid: Entry UUID.
        timestamp: ISO 8601 timestamp string.

    Returns:
        A dict shaped like a real Claude Code JSONL user entry carrying a
        tool_result block.
    """
    return {
        "type": "user",
        "timestamp": timestamp,
        "uuid": uuid,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                }
            ],
        },
    }


def _unit(path: Path) -> AgentTranscript:
    """Build a minimal ``AgentTranscript`` for a general-purpose root agent.

    Args:
        path: Path to the agent's JSONL transcript file.

    Returns:
        An ``AgentTranscript`` pointing at *path* with a single-element
        agent path (no sub-agent nesting).
    """
    return AgentTranscript(
        jsonl_path=path,
        agent_type="general-purpose",
        agent_path=("general-purpose",),
    )


def _session_record(
    session_id: str, root_agent: str = "general-purpose"
) -> SessionRecord:
    """Build a minimal ``SessionRecord`` for ``collect_per_session`` tests.

    Args:
        session_id: Session identifier, also used as the JSONL filename
            stem the caller must place under ``<data_dir>/projects/*/``.
        root_agent: Raw agent-setting value for the root thread.

    Returns:
        A ``SessionRecord`` with no messages (unused by
        ``collect_per_session``, which only reads the transcript on disk).
    """
    return SessionRecord(
        session_id=session_id,
        project="demo",
        project_path="/demo",
        start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
        root_agent=root_agent,
        messages=[],
        subagent_types=[],
    )


class TestCollectToolUses:
    """Behavior of collect_tool_uses over a single agent transcript."""

    def test_parallel_calls_sharing_one_message_id_are_both_counted(
        self, tmp_path: Path
    ) -> None:
        """Regression for spec 4.1: one content block per JSONL line.

        collect_tool_uses must not dedupe by message.id, since the
        real transcript format writes parallel tool calls as separate
        lines that share one message.id.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_b",
                    "Grep",
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl))

        assert [r.tool_name for r in records] == ["Read", "Grep"]

    def test_repeated_tool_use_id_is_counted_once(self, tmp_path: Path) -> None:
        """Same tool_use_id appearing twice dedupes to a single record."""
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        assert len(collect_tool_uses(_unit(jsonl))) == 1

    def test_tool_result_on_user_entry_is_not_counted(self, tmp_path: Path) -> None:
        """A tool_result on a user-type entry is not double-counted."""
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                {
                    "type": "user",
                    "timestamp": "2026-08-01T00:00:02.000Z",
                    "uuid": "u2",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_a",
                                "content": "ok",
                            }
                        ],
                    },
                },
            ],
        )

        assert len(collect_tool_uses(_unit(jsonl))) == 1

    def test_repeated_calls_are_not_collapsed(self, tmp_path: Path) -> None:
        """Frequency is the metric; adjacent duplicates must survive.

        Unlike session_summary.py's existing collector, collect_tool_uses
        keeps every distinct tool_use_id, even when the tool name repeats
        many times in a row.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    f"msg_{i}",
                    f"toolu_{i}",
                    "mcp__codegraph__codegraph_explore",
                    f"u{i}",
                    "2026-08-01T00:00:00.000Z",
                )
                for i in range(10)
            ],
        )

        assert len(collect_tool_uses(_unit(jsonl))) == 10

    def test_unreadable_file_yields_no_records(self, tmp_path: Path) -> None:
        """A missing transcript file yields an empty list, no exception."""
        assert collect_tool_uses(_unit(tmp_path / "missing.jsonl")) == []

    def test_agent_attribution_is_carried_through(self, tmp_path: Path) -> None:
        """Returned records carry the calling agent's type and path."""
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                )
            ],
        )
        unit = AgentTranscript(
            jsonl_path=jsonl,
            agent_type="code-writer",
            agent_path=("general-purpose", "code-writer"),
        )

        record = collect_tool_uses(unit)[0]

        assert record.agent_path == ("general-purpose", "code-writer")
        assert record.agent_type == "code-writer"


class TestCollectToolUsesResultSizes:
    """result_chars tracking (issue #262, D-1=M4, D-4=isolated+secondary-flag).

    All behavior here is opt-in via ``track_mcp_call_sizes=True`` on
    ``collect_tool_uses`` / ``collect_unit``. This mirrors the CLI's new
    ``dashboard --track-mcp-call-sizes`` flag (dest ``track_mcp_call_sizes``,
    default False), which stays entirely separate from the existing
    ``--track-mcp-calls`` flag.
    """

    def test_missing_result_yields_none_not_zero(self, tmp_path: Path) -> None:
        """A tool_use with no matching tool_result gets result_chars=None,
        not 0 -- distinguishable from a present-but-empty result.

        A second tool_use *with* a matching result sits alongside it so
        that ``None`` reads as "not found", not "tracking never wired up".
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_missing",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _tool_use_line(
                    "s",
                    "msg_2",
                    "toolu_found",
                    "mcp__azure__storage",
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
                _user_result_line(
                    "toolu_found",
                    "seventeen chars!!",
                    "u3",
                    "2026-08-01T00:00:02.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        by_id = {r.tool_use_id: r.result_chars for r in records}
        assert by_id == {"toolu_missing": None, "toolu_found": 17}

    def test_string_content_shape_computes_size(self, tmp_path: Path) -> None:
        """A plain-string tool_result.content is measured by character
        count.
        """
        text = "a fairly distinctive result payload"
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line("toolu_a", text, "u2", "2026-08-01T00:00:01.000Z"),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars == len(text)

    def test_empty_string_result_yields_zero_not_none(self, tmp_path: Path) -> None:
        """An empty-but-present string result is 0, not None -- the
        null-vs-zero distinction result_chars exists to carry: None means
        "no tool_result found", 0 means "found, and it was empty".
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line("toolu_a", "", "u2", "2026-08-01T00:00:01.000Z"),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars == 0

    def test_empty_list_content_yields_zero_not_none(self, tmp_path: Path) -> None:
        """An empty-but-present list result -- either zero blocks, or a
        single text block with empty text -- is 0, not None. Checked
        separately from the string-content case since the two shapes go
        through different parsing paths.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a",
                    [{"type": "text", "text": ""}],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars == 0

    def test_list_content_shape_sums_text_blocks(self, tmp_path: Path) -> None:
        """A list-of-blocks tool_result.content sums every text block's
        length, not just the first one.
        """
        first = "block one has some text"
        second = "block two is shorter"
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a",
                    [
                        {"type": "text", "text": first},
                        {"type": "text", "text": second},
                    ],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars == len(first) + len(second)

    def test_image_block_makes_result_size_unknown(self, tmp_path: Path) -> None:
        """A tool_result content list containing an image block must not
        report a small number -- the whole call renders as unknown
        (None), matching the plan's null-vs-zero discipline (§3, §6b):
        excluding image bytes must not make an expensive call look cheap.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a",
                    [
                        {"type": "text", "text": "small caption"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "A" * 10_000,
                            },
                        },
                    ],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars is None, (
            "an image-bearing result must render as unknown (None), not "
            f"a small text-only count -- got {records[0].result_chars!r}"
        )

    def test_unrecognized_block_type_makes_result_size_unknown(
        self, tmp_path: Path
    ) -> None:
        """A tool_result content list containing a block whose type is
        neither ``text`` nor ``image`` must render as unknown (None), not
        as a silently-skipped block that leaves the rest of the sum
        intact. Regression test for PR #270 CodeRabbit review feedback:
        only ``image`` blocks previously forced the unknown path, so any
        other unrecognised block type was skipped rather than
        invalidating the whole result.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a",
                    [{"type": "some_future_block_type", "data": "x" * 10}],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars is None, (
            "an unrecognised block type must render as unknown (None), "
            f"got {records[0].result_chars!r}"
        )

    def test_mixed_text_and_unrecognized_block_makes_result_size_unknown(
        self, tmp_path: Path
    ) -> None:
        """A tool_result content list mixing a measurable text block with
        an unrecognised block must render as unknown (None) overall, not
        as a partial count of just the text block. This is the specific
        undercounting bug flagged in PR #270 review: a mixed result was
        previously returning the text-only partial sum instead of None.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a",
                    [
                        {"type": "text", "text": "this text is measurable"},
                        {"type": "some_future_block_type", "data": "x" * 10},
                    ],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars is None, (
            "a mixed measurable/unsupported result must render as "
            f"unknown (None), not a partial count -- got "
            f"{records[0].result_chars!r}"
        )

    def test_non_dict_block_makes_result_size_unknown(self, tmp_path: Path) -> None:
        """A malformed content list entry that isn't even a dict must
        render as unknown (None), not be silently skipped.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a",
                    ["not a dict block"],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars is None

    def test_text_block_with_non_string_text_makes_result_size_unknown(
        self, tmp_path: Path
    ) -> None:
        """A ``text`` block whose ``text`` field isn't a string must
        render as unknown (None), not silently contribute 0.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a",
                    [{"type": "text", "text": 12345}],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records[0].result_chars is None

    def test_duplicate_tool_use_id_result_size_not_double_counted(
        self, tmp_path: Path
    ) -> None:
        """The existing tool_use_id dedup (:134-138) must not cause the
        matching tool_result's size to be counted more than once.
        """
        text = "unique payload text here"
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
                _user_result_line("toolu_a", text, "u3", "2026-08-01T00:00:02.000Z"),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert len(records) == 1
        assert records[0].result_chars == len(text)

    def test_tool_result_does_not_create_a_new_record(self, tmp_path: Path) -> None:
        """A tool_result on a user entry only annotates an existing
        ToolUseRecord by tool_use_id -- it must never create a new one.
        Guards spec T4 under size-tracking specifically, since a naive
        implementation of the new user-branch could emit a record for
        every tool_result block it visits.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line("toolu_a", "ok", "u2", "2026-08-01T00:00:01.000Z"),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert len(records) == 1
        assert records[0].tool_name == "Read"

    def test_orphan_tool_result_creates_no_record(self, tmp_path: Path) -> None:
        """A tool_result whose tool_use_id matches no tool_use anywhere in
        the file must not create a phantom ToolUseRecord.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _user_result_line(
                    "toolu_never_called",
                    "orphaned result",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl), track_mcp_call_sizes=True)

        assert records == []

    def test_flag_off_by_default_leaves_result_chars_none(self, tmp_path: Path) -> None:
        """Privacy-gating regression guard (D-4): the caller must opt in.
        Calling collect_tool_uses the same way every existing call site in
        this codebase does today (no track_mcp_call_sizes argument at all)
        must leave every record's result_chars at None -- even though a
        real, sizeable tool_result is present in the file. A present result
        that never surfaces is the only externally observable proof that
        the payload was not read when the caller did not ask for it.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a", "x" * 5000, "u2", "2026-08-01T00:00:01.000Z"
                ),
            ],
        )

        records = collect_tool_uses(_unit(jsonl))

        assert records[0].result_chars is None

    def test_collect_unit_also_defaults_result_chars_to_none(
        self, tmp_path: Path
    ) -> None:
        """collect_unit (the merged single-scan entry point) carries the
        same default-off gating as collect_tool_uses.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a", "x" * 5000, "u2", "2026-08-01T00:00:01.000Z"
                ),
            ],
        )

        tool_uses, _availability = collect_unit(_unit(jsonl))

        assert tool_uses[0].result_chars is None

    def test_collect_unit_computes_result_chars_when_opted_in(
        self, tmp_path: Path
    ) -> None:
        """collect_unit computes result_chars when track_mcp_call_sizes is
        explicitly True, matching collect_tool_uses's behavior.
        """
        text = "collect_unit result payload"
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line("toolu_a", text, "u2", "2026-08-01T00:00:01.000Z"),
            ],
        )

        tool_uses, _availability = collect_unit(_unit(jsonl), track_mcp_call_sizes=True)

        assert tool_uses[0].result_chars == len(text)


class TestCollectAvailability:
    """Behavior of collect_availability over a single agent transcript."""

    def test_no_delta_entries_means_signal_absent(self, tmp_path: Path) -> None:
        """No attachment entries at all means the signal is absent."""
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                )
            ],
        )

        result = collect_availability(_unit(jsonl))

        assert result.signal_present is False
        assert result.observed_sources == frozenset()
        assert result.server_sources == {}

    def test_delta_with_only_builtins_still_counts_as_signal(
        self, tmp_path: Path
    ) -> None:
        """Signal presence is independent of any MCP server appearing."""
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _availability_line(
                    "deferred_tools_delta",
                    ["WebFetch", "Monitor"],
                    [],
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                )
            ],
        )

        result = collect_availability(_unit(jsonl))

        assert result.signal_present is True
        assert result.observed_sources == frozenset({"deferred_tools_delta"})
        assert result.server_sources == {}

    def test_deferred_tools_delta_yields_server_names(self, tmp_path: Path) -> None:
        """MCP-shaped names in addedNames resolve to server names."""
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _availability_line(
                    "deferred_tools_delta",
                    ["WebFetch", "mcp__azure__storage", "mcp__azure__acr"],
                    [],
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                )
            ],
        )

        result = collect_availability(_unit(jsonl))

        assert result.signal_present is True
        assert result.server_sources == {"azure": frozenset({"deferred_tools_delta"})}

    def test_removed_names_are_applied_in_file_order(self, tmp_path: Path) -> None:
        """A name added then later removed nets to absent."""
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _availability_line(
                    "deferred_tools_delta",
                    ["mcp__azure__storage"],
                    [],
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _availability_line(
                    "deferred_tools_delta",
                    [],
                    ["mcp__azure__storage"],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        result = collect_availability(_unit(jsonl))

        assert result.signal_present is True
        assert result.server_sources == {}

    def test_union_across_both_sources(self, tmp_path: Path) -> None:
        """deferred_tools_delta and mcp_instructions_delta union together.

        Includes a plugin-scoped name (``plugin:microsoft-docs:microsoft-learn``)
        from mcp_instructions_delta, which must resolve to the server key
        ``microsoft-learn``.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _availability_line(
                    "deferred_tools_delta",
                    ["mcp__azure__storage"],
                    [],
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _availability_line(
                    "mcp_instructions_delta",
                    [
                        "azure",
                        "codegraph",
                        "plugin:microsoft-docs:microsoft-learn",
                    ],
                    [],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        result = collect_availability(_unit(jsonl))

        assert result.server_sources == {
            "azure": frozenset({"deferred_tools_delta", "mcp_instructions_delta"}),
            "codegraph": frozenset({"mcp_instructions_delta"}),
            "microsoft-learn": frozenset({"mcp_instructions_delta"}),
        }


class TestCollectUnit:
    """collect_unit merges the assistant and attachment passes into one scan."""

    def test_returns_availability_for_unit_with_no_attachment_entries(
        self, tmp_path: Path
    ) -> None:
        """An AgentAvailability is returned even with zero attachment
        entries in the file (signal_present stays False, the record is not
        omitted). Pinned directly at collect_unit, not only through its
        collect_tool_uses/collect_availability wrappers.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                )
            ],
        )

        tool_uses, availability = collect_unit(_unit(jsonl))

        assert [r.tool_name for r in tool_uses] == ["Read"]
        assert availability.signal_present is False
        assert availability.server_sources == {}

    def test_matches_the_separate_wrapper_outputs(self, tmp_path: Path) -> None:
        """collect_unit's two outputs equal what the two former standalone
        passes (now thin wrappers) return for the same file.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _availability_line(
                    "deferred_tools_delta",
                    ["mcp__azure__storage"],
                    [],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )
        unit = _unit(jsonl)

        tool_uses, availability = collect_unit(unit)

        assert tool_uses == collect_tool_uses(unit)
        assert availability == collect_availability(unit)


class TestCollectUnitMalformedMessage:
    """Regression: a parseable-but-malformed assistant entry must not crash
    the merged single-scan collect_unit.
    """

    def test_null_message_on_assistant_entry_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """An assistant entry with ``message: null`` is valid, parseable
        JSONL (not a JSON decode error, just a null where a dict was
        assumed). Phase 0 merged the two previously-separate visitor
        passes into collect_unit's single loop; that loop must tolerate
        this shape rather than raising when it calls
        ``entry.get("message", {}).get("content", [])``.

        The malformed entry sits between two valid tool_use entries so a
        correct implementation must both survive it and keep collecting
        the entries that follow it in file order, rather than aborting
        the scan.
        """
        jsonl = tmp_path / "s.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                {
                    "type": "assistant",
                    "timestamp": "2026-08-01T00:00:01.000Z",
                    "sessionId": "s",
                    "uuid": "u2",
                    "message": None,
                },
                _tool_use_line(
                    "s",
                    "msg_2",
                    "toolu_b",
                    "Grep",
                    "u3",
                    "2026-08-01T00:00:02.000Z",
                ),
            ],
        )

        tool_uses, availability = collect_unit(_unit(jsonl))

        assert [r.tool_name for r in tool_uses] == ["Read", "Grep"]
        assert availability.signal_present is False


class TestCollectPerSession:
    """collect_per_session: session-list collection plus record filters."""

    def test_tool_and_server_both_set_tool_wins(self, tmp_path: Path) -> None:
        """Reproduces cli/tool_usage.py's silent elif precedence: when both
        --tool and --server are supplied, tool wins and server is ignored.
        """
        jsonl = tmp_path / "projects" / "demo-proj" / "s1.jsonl"
        jsonl.parent.mkdir(parents=True)
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s1",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _tool_use_line(
                    "s1",
                    "msg_2",
                    "toolu_b",
                    "mcp__azure__storage",
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )
        sessions = [_session_record("s1")]

        per_session, skipped = collect_per_session(
            sessions, tmp_path, tool="Read", server="azure"
        )

        assert skipped == 0
        _, tool_uses, _ = per_session[0]
        assert [r.tool_name for r in tool_uses] == ["Read"]

    def test_agent_filter_applies_to_both_tool_uses_and_availabilities(
        self, tmp_path: Path
    ) -> None:
        """--agent filters both tool_uses and availabilities, unlike
        --tool/--server, which filter only tool_uses.
        """
        jsonl = tmp_path / "projects" / "demo-proj" / "s1.jsonl"
        jsonl.parent.mkdir(parents=True)
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s1",
                    "msg_1",
                    "toolu_a",
                    "Read",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _availability_line(
                    "deferred_tools_delta",
                    ["mcp__azure__storage"],
                    [],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )
        sessions = [_session_record("s1", root_agent="general-purpose")]

        matched, _ = collect_per_session(sessions, tmp_path, agent="general-purpose")
        unmatched, _ = collect_per_session(sessions, tmp_path, agent="no-such-agent")

        _, matched_tool_uses, matched_availabilities = matched[0]
        _, unmatched_tool_uses, unmatched_availabilities = unmatched[0]

        assert len(matched_tool_uses) == 1
        assert len(matched_availabilities) == 1
        assert unmatched_tool_uses == []
        assert unmatched_availabilities == []

    def test_missing_transcript_is_skipped(self, tmp_path: Path) -> None:
        """A session with no matching JSONL file increments skipped,
        rather than raising.
        """
        sessions = [_session_record("missing-session")]

        per_session, skipped = collect_per_session(sessions, tmp_path)

        assert per_session == []
        assert skipped == 1


class TestCollectSessionResultSizes:
    """collect_session threading of track_mcp_call_sizes (issue #262 Phase
    3 wiring). Neither this parameter nor any equivalent gating exists on
    collect_session before this phase -- it forwards to collect_unit
    unconditionally today, so every test below is a red until the keyword
    is added and threaded through.
    """

    def test_true_computes_result_chars_through_to_collect_unit(
        self, tmp_path: Path
    ) -> None:
        """track_mcp_call_sizes=True on collect_session must reach
        collect_unit and produce a measured result_chars, proving the
        keyword is not merely accepted-and-ignored.
        """
        text = "collect_session result payload"
        jsonl = tmp_path / "s1.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s1",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line("toolu_a", text, "u2", "2026-08-01T00:00:01.000Z"),
            ],
        )

        tool_uses, _availabilities = collect_session(
            jsonl, "general-purpose", track_mcp_call_sizes=True
        )

        assert tool_uses[0].result_chars == len(text)

    def test_default_leaves_result_chars_none(self, tmp_path: Path) -> None:
        """Calling collect_session exactly as every pre-Phase-3 call site
        does (no track_mcp_call_sizes argument) must leave result_chars at
        None, matching collect_unit's own default-off gating -- even
        though a real, sizeable tool_result is present in the file.
        """
        jsonl = tmp_path / "s1.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s1",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a", "x" * 5000, "u2", "2026-08-01T00:00:01.000Z"
                ),
            ],
        )

        tool_uses, _availabilities = collect_session(jsonl, "general-purpose")

        assert tool_uses[0].result_chars is None

    def test_image_block_result_differs_true_vs_false(self, tmp_path: Path) -> None:
        """A transcript with an image-bearing tool_result must behave
        differently under the two kwarg values when reached through
        collect_session, not only through collect_unit directly: off
        leaves result_chars/result_excluded at their record defaults
        (never inspected), on renders result_chars=None with
        result_excluded=True (unmeasurable content, not "not found").
        """
        jsonl = tmp_path / "s1.jsonl"
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s1",
                    "msg_1",
                    "toolu_a",
                    "mcp__codegraph__codegraph_explore",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a",
                    [
                        {"type": "text", "text": "small caption"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "A" * 10_000,
                            },
                        },
                    ],
                    "u2",
                    "2026-08-01T00:00:01.000Z",
                ),
            ],
        )

        off_tool_uses, _ = collect_session(jsonl, "general-purpose")
        on_tool_uses, _ = collect_session(
            jsonl, "general-purpose", track_mcp_call_sizes=True
        )

        assert off_tool_uses[0].result_chars is None
        assert off_tool_uses[0].result_excluded is False
        assert on_tool_uses[0].result_chars is None
        assert on_tool_uses[0].result_excluded is True


class TestCollectPerSessionResultSizes:
    """collect_per_session threading of track_mcp_call_sizes (issue #262
    Phase 3 wiring). Neither this parameter nor any equivalent gating
    exists on collect_per_session before this phase.
    """

    def test_true_computes_result_chars_through_to_collect_session(
        self, tmp_path: Path
    ) -> None:
        """track_mcp_call_sizes=True on collect_per_session must reach
        collect_session (and, through it, collect_unit) and produce a
        measured result_chars on the returned records.
        """
        text = "collect_per_session result payload"
        jsonl = tmp_path / "projects" / "demo-proj" / "s1.jsonl"
        jsonl.parent.mkdir(parents=True)
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s1",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line("toolu_a", text, "u2", "2026-08-01T00:00:01.000Z"),
            ],
        )
        sessions = [_session_record("s1")]

        per_session, _skipped = collect_per_session(
            sessions, tmp_path, track_mcp_call_sizes=True
        )

        _, tool_uses, _availabilities = per_session[0]
        assert tool_uses[0].result_chars == len(text)

    def test_default_leaves_result_chars_none(self, tmp_path: Path) -> None:
        """Calling collect_per_session exactly as every pre-Phase-3 call
        site does (no track_mcp_call_sizes argument) must leave
        result_chars at None, even though a real, sizeable tool_result is
        present in the file -- proving the default stays privacy-off all
        the way through this call chain, not just at collect_unit.
        """
        jsonl = tmp_path / "projects" / "demo-proj" / "s1.jsonl"
        jsonl.parent.mkdir(parents=True)
        _write_jsonl(
            jsonl,
            [
                _tool_use_line(
                    "s1",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:00.000Z",
                ),
                _user_result_line(
                    "toolu_a", "x" * 5000, "u2", "2026-08-01T00:00:01.000Z"
                ),
            ],
        )
        sessions = [_session_record("s1")]

        per_session, _skipped = collect_per_session(sessions, tmp_path)

        _, tool_uses, _availabilities = per_session[0]
        assert tool_uses[0].result_chars is None
