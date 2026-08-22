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
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_prospector.tool_collection import collect_availability, collect_tool_uses
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
