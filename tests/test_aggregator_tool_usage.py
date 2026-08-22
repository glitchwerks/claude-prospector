"""Tests for compute_tool_usage.

Covers:
- by_tool: builtins and MCP tools counted by raw name.
- by_server: availability-but-never-called reports zero (not missing),
  null sessions_seen_in when no signal exists anywhere, avg_calls_per_active
  session is per-active-session, by_method splits calls to the same server,
  and availability unions across every agent within one session (D8(a)).
- by_agent: default shape keys by full agent path and raw tool name;
  compact=True buckets built-ins under a single count and keys MCP calls by
  server name; compact only changes by_agent, never by_tool/by_server.
- warnings/availability_signal: a malformed MCP-shaped name counts in
  by_tool, is excluded from by_server, and increments
  warnings.malformed_mcp_names; availability_signal reports session and
  source coverage correctly, including when a built-ins-only delta still
  proves the inventory was visible.
"""

from __future__ import annotations

from claude_prospector.aggregator import compute_tool_usage
from claude_prospector.models import AgentAvailability, ToolUseRecord


def _use(tool: str, path: tuple[str, ...] = ("general-purpose",)) -> ToolUseRecord:
    """Build a ToolUseRecord for a single tool call.

    Args:
        tool: Raw tool name as it would appear in a transcript.
        path: Full agent-path ancestry tuple that issued the call.

    Returns:
        A ToolUseRecord with an empty tool_use_id (irrelevant to
        aggregation) and agent_type derived from the leaf of *path*.
    """
    return ToolUseRecord(
        tool_name=tool, tool_use_id="", agent_type=path[-1], agent_path=path
    )


def _avail(
    servers: dict[str, frozenset[str]],
    path: tuple[str, ...] = ("general-purpose",),
    signal: bool = True,
) -> AgentAvailability:
    """Build an AgentAvailability record for one agent.

    Args:
        servers: The server_sources mapping for this agent.
        path: Full agent-path ancestry tuple.
        signal: Whether an availability signal was observed at all. When
            False, observed_sources is empty (signal absent) regardless of
            *servers*.

    Returns:
        An AgentAvailability record.
    """
    return AgentAvailability(
        agent_path=path,
        observed_sources=(
            frozenset({"deferred_tools_delta"}) if signal else frozenset()
        ),
        server_sources=servers,
    )


class TestByTool:
    def test_builtins_and_mcp_are_both_counted_by_raw_name(self) -> None:
        result = compute_tool_usage(
            [("s1", [_use("Read"), _use("Read"), _use("mcp__azure__storage")], [])]
        )

        assert result["by_tool"] == {"Read": 2, "mcp__azure__storage": 1}


class TestByServer:
    def test_available_but_never_called_is_zero_not_missing(self) -> None:
        result = compute_tool_usage(
            [("s1", [], [_avail({"azure": frozenset({"deferred_tools_delta"})})])]
        )

        assert result["by_server"]["azure"] == {
            "total_calls": 0,
            "sessions_seen_in": 1,
            "sessions_used_in": 0,
            "avg_calls_per_active_session": None,
            "by_method": {},
        }

    def test_no_signal_anywhere_yields_null_seen_in(self) -> None:
        result = compute_tool_usage(
            [("s1", [_use("mcp__azure__storage")], [_avail({}, signal=False)])]
        )

        assert result["by_server"]["azure"]["sessions_seen_in"] is None
        assert result["by_server"]["azure"]["sessions_used_in"] == 1

    def test_avg_is_per_active_session(self) -> None:
        result = compute_tool_usage(
            [
                (
                    "s1",
                    [_use("mcp__azure__storage")] * 3,
                    [_avail({"azure": frozenset({"deferred_tools_delta"})})],
                ),
                (
                    "s2",
                    [],
                    [_avail({"azure": frozenset({"deferred_tools_delta"})})],
                ),
            ]
        )

        server = result["by_server"]["azure"]
        assert server["total_calls"] == 3
        assert server["sessions_seen_in"] == 2
        assert server["sessions_used_in"] == 1
        assert server["avg_calls_per_active_session"] == 3.0

    def test_by_method_splits_a_multi_tool_server(self) -> None:
        result = compute_tool_usage(
            [
                (
                    "s1",
                    [
                        _use("mcp__azure__storage"),
                        _use("mcp__azure__acr"),
                        _use("mcp__azure__acr"),
                    ],
                    [],
                )
            ]
        )

        assert result["by_server"]["azure"]["by_method"] == {"storage": 1, "acr": 2}

    def test_availability_unions_across_agents_in_one_session(self) -> None:
        """Spec D8(a): seen by ANY agent counts for the session."""
        result = compute_tool_usage(
            [
                (
                    "s1",
                    [],
                    [
                        _avail({}, path=("general-purpose",)),
                        _avail(
                            {"codegraph": frozenset({"deferred_tools_delta"})},
                            path=("general-purpose", "code-writer"),
                        ),
                    ],
                )
            ]
        )

        assert result["by_server"]["codegraph"]["sessions_seen_in"] == 1


class TestByAgent:
    def test_default_shape_is_agent_by_raw_tool(self) -> None:
        result = compute_tool_usage(
            [
                (
                    "s1",
                    [
                        _use("Read"),
                        _use(
                            "mcp__azure__storage",
                            ("general-purpose", "code-writer"),
                        ),
                    ],
                    [],
                )
            ]
        )

        assert result["by_agent"] == {
            "general-purpose": {"Read": 1},
            "general-purpose→code-writer": {"mcp__azure__storage": 1},
        }

    def test_compact_shape_buckets_builtins_and_keys_by_server(self) -> None:
        result = compute_tool_usage(
            [("s1", [_use("Read"), _use("Grep"), _use("mcp__azure__storage")], [])],
            compact=True,
        )

        assert result["by_agent"] == {"general-purpose": {"_builtin": 2, "azure": 1}}

    def test_compact_does_not_change_by_tool_or_by_server(self) -> None:
        records = [("s1", [_use("Read"), _use("mcp__azure__storage")], [])]

        full = compute_tool_usage(records)
        compact = compute_tool_usage(records, compact=True)

        assert full["by_tool"] == compact["by_tool"]
        assert full["by_server"] == compact["by_server"]


class TestWarningsAndSignal:
    def test_malformed_mcp_name_counts_in_by_tool_not_by_server(self) -> None:
        result = compute_tool_usage([("s1", [_use("mcp__broken")], [])])

        assert result["by_tool"] == {"mcp__broken": 1}
        assert result["by_server"] == {}
        assert result["warnings"]["malformed_mcp_names"] == 1

    def test_signal_coverage_is_reported(self) -> None:
        result = compute_tool_usage(
            [
                ("s1", [], [_avail({"azure": frozenset({"deferred_tools_delta"})})]),
                ("s2", [], [_avail({}, signal=False)]),
            ]
        )

        assert result["availability_signal"]["sessions_with_signal"] == 1
        assert result["availability_signal"]["sessions_without_signal"] == 1
        assert result["availability_signal"]["by_server_sources"] == {
            "azure": ["deferred_tools_delta"]
        }

    def test_sources_is_populated_even_when_no_server_was_named(self) -> None:
        """A built-ins-only delta still proves the inventory was visible."""
        result = compute_tool_usage([("s1", [], [_avail({})])])

        assert result["availability_signal"]["sessions_with_signal"] == 1
        assert result["availability_signal"]["sources"] == ["deferred_tools_delta"]
        assert result["availability_signal"]["by_server_sources"] == {}
