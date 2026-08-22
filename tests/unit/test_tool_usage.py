"""Tests for the tool-usage subcommand.

Covers:
- Reports calls and availability correctly for a session with both a
  deferred_tools_delta availability entry and real tool calls.
- --server filters by_tool down to just that server's calls.
- --compact changes only by_agent, not by_tool/by_server.
- An empty data directory is not an error.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from claude_prospector.cli import tool_usage

# ---------------------------------------------------------------------------
# Local fixture builders (this repo's convention: each test file defines its
# own JSONL builders rather than importing from another test file or
# conftest.py). Copied verbatim from tests/unit/test_tool_collection.py.
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


def _make_session(data_dir: Path, session_id: str, lines: list[dict]) -> None:
    """Write a synthetic session JSONL under a fake project directory.

    Args:
        data_dir: Root Claude data directory (a tmp_path in tests).
        session_id: Session identifier; used as the JSONL filename stem.
        lines: JSONL entries to write, in order.
    """
    project_dir = data_dir / "projects" / "I--ai-demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(project_dir / f"{session_id}.jsonl", lines)


def _run(capsys, **overrides) -> dict:
    """Build a Namespace, run the subcommand, and parse its JSON stdout.

    Args:
        capsys: pytest's capsys fixture, used to capture stdout.
        **overrides: Namespace fields to override from the defaults.

    Returns:
        The parsed JSON report emitted on stdout.
    """
    args = argparse.Namespace(
        data_dir=overrides.pop("data_dir"),
        days=overrides.pop("days", 3650),
        from_date=None,
        to_date=None,
        repo=None,
        agent=None,
        tool=None,
        server=None,
        compact=False,
        format="json",
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    assert tool_usage.run(args) == tool_usage.EXIT_OK
    return json.loads(capsys.readouterr().out)


class TestRun:
    def test_reports_calls_and_availability(self, tmp_path: Path, capsys) -> None:
        _make_session(
            tmp_path,
            "sess-a",
            [
                {
                    "type": "agent-setting",
                    "agentSetting": "main",
                    "sessionId": "sess-a",
                },
                _availability_line(
                    "deferred_tools_delta",
                    ["mcp__azure__storage", "mcp__codegraph__codegraph_explore"],
                    [],
                    "u0",
                    "2026-08-01T00:00:00.000Z",
                ),
                _tool_use_line(
                    "sess-a",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:01.000Z",
                ),
                _tool_use_line(
                    "sess-a",
                    "msg_1",
                    "toolu_b",
                    "Read",
                    "u2",
                    "2026-08-01T00:00:02.000Z",
                ),
            ],
        )

        report = _run(capsys, data_dir=tmp_path)

        assert report["by_tool"] == {"mcp__azure__storage": 1, "Read": 1}
        assert report["by_server"]["azure"]["total_calls"] == 1
        assert report["by_server"]["codegraph"]["total_calls"] == 0
        assert report["by_server"]["codegraph"]["sessions_seen_in"] == 1
        assert report["window"]["sessions"] == 1
        assert report["compact"] is False

    def test_server_filter_narrows_by_tool(self, tmp_path: Path, capsys) -> None:
        _make_session(
            tmp_path,
            "sess-b",
            [
                {
                    "type": "agent-setting",
                    "agentSetting": "main",
                    "sessionId": "sess-b",
                },
                _tool_use_line(
                    "sess-b",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:01.000Z",
                ),
                _tool_use_line(
                    "sess-b",
                    "msg_1",
                    "toolu_b",
                    "Read",
                    "u2",
                    "2026-08-01T00:00:02.000Z",
                ),
            ],
        )

        report = _run(capsys, data_dir=tmp_path, server="azure")

        assert report["by_tool"] == {"mcp__azure__storage": 1}

    def test_compact_changes_only_by_agent(self, tmp_path: Path, capsys) -> None:
        _make_session(
            tmp_path,
            "sess-c",
            [
                {
                    "type": "agent-setting",
                    "agentSetting": "main",
                    "sessionId": "sess-c",
                },
                _tool_use_line(
                    "sess-c",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:01.000Z",
                ),
                _tool_use_line(
                    "sess-c",
                    "msg_1",
                    "toolu_b",
                    "Read",
                    "u2",
                    "2026-08-01T00:00:02.000Z",
                ),
            ],
        )

        full = _run(capsys, data_dir=tmp_path)
        compact = _run(capsys, data_dir=tmp_path, compact=True)

        assert full["by_tool"] == compact["by_tool"]
        assert full["by_server"] == compact["by_server"]
        assert compact["by_agent"] == {"main": {"_builtin": 1, "azure": 1}}
        assert compact["compact"] is True

    def test_empty_data_dir_is_not_an_error(self, tmp_path: Path, capsys) -> None:
        report = _run(capsys, data_dir=tmp_path)

        assert report["by_tool"] == {}
        assert report["window"]["sessions"] == 0
