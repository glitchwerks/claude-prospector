"""Tests for the tool-usage subcommand.

Covers:
- Reports calls and availability correctly for a session with both a
  deferred_tools_delta availability entry and real tool calls.
- --server filters by_tool down to just that server's calls.
- --compact changes only by_agent, not by_tool/by_server.
- An empty data directory is not an error.
- --server matches the server component exactly, not as an fnmatch
  substring/prefix (CodeRabbit review on PR #252, Behavior A).
- --to-alone anchors the relative --days window to --to, not to "now"
  (CodeRabbit review on PR #252, Behavior B).
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
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


class TestServerFilterExactMatch:
    """CodeRabbit review on PR #252, Behavior A.

    ``--server`` must match the server component of an MCP tool name
    exactly (after normalization), not as an fnmatch substring/prefix.
    ``--tool`` (the raw glob filter) is unrelated and keeps its existing
    substring/glob semantics.
    """

    def _make_three_server_session(self, tmp_path: Path) -> None:
        """Write one session with azure, myazure, and azure2 tool calls.

        Args:
            tmp_path: Root Claude data directory (a tmp_path in tests).
        """
        _make_session(
            tmp_path,
            "sess-server-exact",
            [
                {
                    "type": "agent-setting",
                    "agentSetting": "main",
                    "sessionId": "sess-server-exact",
                },
                _tool_use_line(
                    "sess-server-exact",
                    "msg_1",
                    "toolu_a",
                    "mcp__azure__storage",
                    "u1",
                    "2026-08-01T00:00:01.000Z",
                ),
                _tool_use_line(
                    "sess-server-exact",
                    "msg_2",
                    "toolu_b",
                    "mcp__myazure__storage",
                    "u2",
                    "2026-08-01T00:00:02.000Z",
                ),
                _tool_use_line(
                    "sess-server-exact",
                    "msg_3",
                    "toolu_c",
                    "mcp__azure2__thing",
                    "u3",
                    "2026-08-01T00:00:03.000Z",
                ),
            ],
        )

    def test_server_filter_includes_exact_server_name(
        self, tmp_path: Path, capsys
    ) -> None:
        """--server azure must include calls to mcp__azure__storage."""
        self._make_three_server_session(tmp_path)

        report = _run(capsys, data_dir=tmp_path, days=3650, server="azure")

        assert "mcp__azure__storage" in report["by_tool"]

    def test_server_filter_excludes_prefix_swallowed_name(
        self, tmp_path: Path, capsys
    ) -> None:
        """--server azure must not match mcp__myazure__storage.

        Regression case for the fnmatch pattern ``mcp__*azure__*``, whose
        leading ``*`` swallows the ``my`` prefix and produces a
        false-positive match.
        """
        self._make_three_server_session(tmp_path)

        report = _run(capsys, data_dir=tmp_path, days=3650, server="azure")

        assert "mcp__myazure__storage" not in report["by_tool"], (
            "mcp__myazure__storage should not match --server azure "
            f"exactly, got by_tool={report['by_tool']!r}"
        )

    def test_server_filter_excludes_differently_named_server(
        self, tmp_path: Path, capsys
    ) -> None:
        """--server azure must not match a differently-named azure2 server.

        The server component must match exactly after normalization, not
        merely share a leading substring with the requested server name.
        """
        self._make_three_server_session(tmp_path)

        report = _run(capsys, data_dir=tmp_path, days=3650, server="azure")

        assert "mcp__azure2__thing" not in report["by_tool"], (
            "mcp__azure2__thing should not match --server azure exactly, "
            f"got by_tool={report['by_tool']!r}"
        )

    def test_tool_glob_filter_unaffected_by_server_exact_match_fix(
        self, tmp_path: Path, capsys
    ) -> None:
        """--tool keeps its raw fnmatch glob semantics, unrelated to --server.

        Regression guard: fixing --server's exact-match semantics must not
        touch --tool's existing substring/glob matching, which is expected
        (not a bug) to match both mcp__azure__storage and
        mcp__myazure__storage for the glob ``mcp__*azure__*``.
        """
        self._make_three_server_session(tmp_path)

        report = _run(capsys, data_dir=tmp_path, days=3650, tool="mcp__*azure__*")

        assert "mcp__azure__storage" in report["by_tool"]
        assert "mcp__myazure__storage" in report["by_tool"]


class TestWindowBoundsToAnchor:
    """CodeRabbit review on PR #252, Behavior B.

    When only ``--to`` is given (no ``--from``), the relative ``--days``
    window must be anchored to ``--to``, not to "now" -- and the
    already-correct ``--from``/``--to``/``--days``-only paths must not
    change. The inverted-window rejection case (both --from and --to given,
    --from after --to) is a CLI-level exit-code/stderr assertion and lives
    in tests/test_cli_subcommands.py::TestToolUsageSubcommand instead.
    """

    def test_to_alone_anchors_default_days_window_to_to_date(
        self, tmp_path: Path, capsys
    ) -> None:
        """--to alone (no --from), default --days 7, anchors to --to.

        The window start must be 7 days before --to, not 7 days before
        "now".
        """
        report = _run(capsys, data_dir=tmp_path, days=7, to_date=datetime(2026, 1, 1))

        assert report["window"]["start"] == "2025-12-25"
        assert report["window"]["end"] == "2026-01-01"

    def test_to_alone_with_explicit_days_anchors_to_to_date(
        self, tmp_path: Path, capsys
    ) -> None:
        """--to alone with an explicit --days N still anchors to --to."""
        report = _run(capsys, data_dir=tmp_path, days=3, to_date=datetime(2026, 1, 1))

        assert report["window"]["start"] == "2025-12-29"
        assert report["window"]["end"] == "2026-01-01"

    def test_from_before_to_uses_explicit_window_unchanged(
        self, tmp_path: Path, capsys
    ) -> None:
        """Both --from and --to given, --from before --to: window is exact.

        Regression guard: today's --from + --to behavior is already correct
        and must not change.
        """
        report = _run(
            capsys,
            data_dir=tmp_path,
            from_date=datetime(2026, 1, 1),
            to_date=datetime(2026, 2, 1),
        )

        assert report["window"]["start"] == "2026-01-01"
        assert report["window"]["end"] == "2026-02-01"

    def test_days_only_default_path_is_unaffected(self, tmp_path: Path, capsys) -> None:
        """No --from, no --to: the existing now-minus-days path is unaffected.

        Regression guard for the pre-existing default path. Asserted
        relative to today's date rather than a literal, since this is the
        one case that legitimately depends on "now".
        """
        report = _run(capsys, data_dir=tmp_path, days=3)

        expected_start = (date.today() - timedelta(days=3)).isoformat()
        assert report["window"]["start"] == expected_start
        assert report["window"]["end"] is None
