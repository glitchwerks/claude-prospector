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
- cost attribution (issue #262 Phase 2, D-1=M4): per-server and per-method
  ``estimated_result_tokens`` (with a mean-per-call stat, not just a bare
  total), an additive ``by_method_tokens`` map that leaves the existing
  ``by_method`` call-count field untouched, and a ``cost_attribution``
  block distinguishing "no result found" from "result found but
  unmeasurable" -- see ``TestCostAttribution`` below for the interface
  this pins down, since that distinction does not exist on
  ``ToolUseRecord`` yet.
"""

from __future__ import annotations

from itertools import count

from claude_prospector.aggregator import compute_tool_usage
from claude_prospector.models import AgentAvailability, ToolUseRecord

_tool_use_id_counter = count(1)


def _use(tool: str, path: tuple[str, ...] = ("general-purpose",)) -> ToolUseRecord:
    """Build a ToolUseRecord for a single tool call.

    Args:
        tool: Raw tool name as it would appear in a transcript.
        path: Full agent-path ancestry tuple that issued the call.

    Returns:
        A ToolUseRecord with a real, distinct auto-generated tool_use_id.
        compute_tool_usage does not read tool_use_id today, but issue
        #262 (D-1=M4) makes it a join key for result-size annotation in
        tool_collection.collect_unit, so fixtures here use real ids
        rather than a shared empty string.

        Used bare (no result data), this fixture also stands in for the
        "no tool_result found at all" case in the cost-attribution tests
        below -- ``result_chars`` stays at its default ``None`` and no
        exclusion is flagged.
    """
    return ToolUseRecord(
        tool_name=tool,
        tool_use_id=f"toolu_test_{next(_tool_use_id_counter)}",
        agent_type=path[-1],
        agent_path=path,
    )


def _use_measured(
    tool: str,
    result_chars: int,
    path: tuple[str, ...] = ("general-purpose",),
) -> ToolUseRecord:
    """Build a ToolUseRecord whose ``tool_result`` was found and measured.

    Args:
        tool: Raw tool name as it would appear in a transcript.
        result_chars: Character length of the (simulated) tool_result
            payload. Callers should pick multiples of 4 so the
            chars-per-token=4.0 conversion lands on an exact token count,
            keeping assertions free of rounding ambiguity.
        path: Full agent-path ancestry tuple that issued the call.

    Returns:
        A ToolUseRecord with ``result_chars`` set to a measured value.
        Exercises the existing (Phase 1) field -- no interface gap here.
    """
    return ToolUseRecord(
        tool_name=tool,
        tool_use_id=f"toolu_test_{next(_tool_use_id_counter)}",
        agent_type=path[-1],
        agent_path=path,
        result_chars=result_chars,
    )


def _use_excluded(
    tool: str,
    path: tuple[str, ...] = ("general-purpose",),
) -> ToolUseRecord:
    """Build a ToolUseRecord whose ``tool_result`` was found but unmeasurable.

    ASSUMED INTERFACE -- does not exist yet: Phase 1's ``result_chars:
    int | None`` collapses "no tool_result was ever found for this
    tool_use_id" and "a tool_result was found but its content was
    unmeasurable (e.g. an image block)" into the same ``None`` value
    (models.py's own docstring says as much). Phase 2's
    ``cost_attribution`` block requires these as two separate counters
    (``calls_without_result`` vs ``calls_with_excluded_content``), which
    ``result_chars`` alone cannot distinguish.

    This fixture pins the distinguishing interface this test suite
    expects: a new defaulted ``ToolUseRecord`` field,
    ``result_excluded: bool = False``, set True exactly when a
    ``tool_result`` was located but its content was excluded as
    unmeasurable. ``result_chars`` stays ``None`` in that case (a
    measured value and an excluded flag are mutually exclusive).

    This is a *test fixture* pinning an expected field, not a
    implementation of the collection-layer logic that would set it in
    tool_collection.py -- that logic (deciding excluded vs missing
    while scanning ``tool_result`` blocks) is the implementer's to
    design. Until ``ToolUseRecord`` gains this field, constructing this
    fixture raises ``TypeError: unexpected keyword argument
    'result_excluded'`` -- that TypeError is itself the expected red for
    the tests that use this helper (see ``TestCostAttribution``).

    Args:
        tool: Raw tool name as it would appear in a transcript.
        path: Full agent-path ancestry tuple that issued the call.

    Returns:
        A ToolUseRecord with ``result_excluded=True`` and
        ``result_chars=None``.
    """
    return ToolUseRecord(
        tool_name=tool,
        tool_use_id=f"toolu_test_{next(_tool_use_id_counter)}",
        agent_type=path[-1],
        agent_path=path,
        result_excluded=True,  # type: ignore[call-arg]
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
                    [_use("mcp__azure__storage") for _ in range(3)],
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

    def test_warnings_no_longer_flags_workflow_agents_as_unattributed(self) -> None:
        """Regression guard for issue #253.

        The transcript walker now traverses ``subagents/workflows/wf_*/``,
        so workflow-dispatched agents are attributable like any other
        subagent. The stale ``workflow_agents_unattributed`` flag must not
        reappear in the ``warnings`` payload.
        """
        result = compute_tool_usage([("s1", [_use("Read")], [])])

        assert "workflow_agents_unattributed" not in result["warnings"]

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


class TestCostAttributionGating:
    """Requirement 4: cost fields only appear when tracking was opted into.

    ASSUMED INTERFACE: ``compute_tool_usage`` gains a new keyword-only
    parameter, ``track_mcp_call_sizes: bool = False``, mirroring
    ``tool_collection.collect_unit``'s parameter of the same name. This
    is deliberately an explicit parameter rather than something inferred
    from whether any record happens to carry ``result_chars`` data,
    because inference cannot be made deterministic: a caller that opted
    into tracking but whose calls all happened to have no matching
    result (all ``result_chars is None``) would be indistinguishable
    from a caller that never opted in at all, if the gate is data-driven.
    """

    def test_cost_fields_absent_when_tracking_not_requested(self) -> None:
        """Default call (no flag) leaves the base call-count path alone."""
        result = compute_tool_usage(
            [("s1", [_use("mcp__azure__storage"), _use("Read")], [])]
        )

        assert "cost_attribution" not in result
        assert "estimated_result_tokens" not in result["by_server"]["azure"]
        assert "by_method_tokens" not in result["by_server"]["azure"]
        # Base behavior is completely unaffected.
        assert result["by_tool"] == {"mcp__azure__storage": 1, "Read": 1}
        assert result["by_server"]["azure"]["by_method"] == {"storage": 1}

    def test_flag_gates_output_even_when_records_carry_result_data(self) -> None:
        """The explicit flag is authoritative, not merely data presence.

        A record can carry a measured ``result_chars`` (e.g. because a
        caller pre-built records with tracking data) while the caller
        still declines cost-attribution output for this particular
        call, by leaving ``track_mcp_call_sizes`` at its default.
        """
        result = compute_tool_usage(
            [("s1", [_use_measured("mcp__azure__storage", 400)], [])]
        )

        assert "cost_attribution" not in result
        assert "estimated_result_tokens" not in result["by_server"]["azure"]

    def test_cost_fields_present_when_tracking_requested(self) -> None:
        result = compute_tool_usage(
            [("s1", [_use_measured("mcp__azure__storage", 400)], [])],
            track_mcp_call_sizes=True,
        )

        assert "cost_attribution" in result
        assert "estimated_result_tokens" in result["by_server"]["azure"]


class TestEstimatedResultTokens:
    """Per-server and per-method token totals, plus a per-call stat.

    Fixture uses chars that are exact multiples of 4 (400, 800, 3600) so
    the chars_per_token=4.0 conversion lands on exact token counts (100,
    200, 900) with no rounding ambiguity, and deliberately picks values
    where mean (400.0) and median (200.0) differ so a test asserting the
    mean cannot be accidentally satisfied by a median implementation (or
    vice versa).

    ASSUMED STATISTIC: this suite pins **mean** per call
    (``mean_result_tokens_per_call``) as the required per-call stat,
    not median. The plan text says "median or mean" without preferring
    one; mean is simpler to compute deterministically (no sort/ordering
    policy for ties) and is the choice pinned here. If the implementer
    prefers median, that is a test-dispute to raise back to this suite's
    author, not something to change unilaterally.
    """

    def _three_azure_calls(self):
        return [
            _use_measured("mcp__azure__storage", 400),  # 100 tokens
            _use_measured("mcp__azure__storage", 800),  # 200 tokens
            _use_measured("mcp__azure__acr", 3600),  # 900 tokens
        ]

    def test_per_server_total_and_mean_per_call(self) -> None:
        result = compute_tool_usage(
            [("s1", self._three_azure_calls(), [])],
            track_mcp_call_sizes=True,
        )

        tokens = result["by_server"]["azure"]["estimated_result_tokens"]
        assert tokens["total"] == 1200.0
        assert tokens["mean_result_tokens_per_call"] == 400.0

    def test_per_method_totals_are_additive_and_do_not_replace_by_method(
        self,
    ) -> None:
        result = compute_tool_usage(
            [("s1", self._three_azure_calls(), [])],
            track_mcp_call_sizes=True,
        )

        server = result["by_server"]["azure"]
        # Existing call-count field: unchanged shape, dict[str, int].
        assert server["by_method"] == {"storage": 2, "acr": 1}
        # New, additive per-method token map.
        assert server["by_method_tokens"] == {
            "storage": {"total": 300.0, "mean_result_tokens_per_call": 150.0},
            "acr": {"total": 900.0, "mean_result_tokens_per_call": 900.0},
        }

    def test_aggregates_across_multiple_sessions(self) -> None:
        result = compute_tool_usage(
            [
                ("s1", [_use_measured("mcp__azure__storage", 400)], []),
                ("s2", [_use_measured("mcp__azure__storage", 800)], []),
            ],
            track_mcp_call_sizes=True,
        )

        tokens = result["by_server"]["azure"]["estimated_result_tokens"]
        assert tokens["total"] == 300.0
        assert tokens["mean_result_tokens_per_call"] == 150.0

    def test_by_method_call_count_shape_is_unchanged_regression_guard(self) -> None:
        """Regression guard: ``by_method`` stays dict[str, int].

        The plan explicitly warns against widening ``by_method``'s
        values to objects, since the shipped view iterates it as
        ``[method, count]`` pairs. This must hold whether or not size
        tracking is requested.
        """
        no_tracking = compute_tool_usage([("s1", self._three_azure_calls(), [])])
        with_tracking = compute_tool_usage(
            [("s1", self._three_azure_calls(), [])],
            track_mcp_call_sizes=True,
        )

        expected = {"storage": 2, "acr": 1}
        assert no_tracking["by_server"]["azure"]["by_method"] == expected
        assert with_tracking["by_server"]["azure"]["by_method"] == expected
        for count_value in with_tracking["by_server"]["azure"]["by_method"].values():
            assert isinstance(count_value, int)

    def test_server_with_no_measured_calls_reports_zero_total_and_null_mean(
        self,
    ) -> None:
        """No measured calls -> total 0.0, mean None (not a ZeroDivisionError).

        Mirrors the existing ``avg_calls_per_active_session`` precedent
        (``None`` when there is no active-session denominator to divide
        by), rather than inventing a new null convention.
        """
        result = compute_tool_usage(
            [("s1", [_use("mcp__azure__storage")], [])],
            track_mcp_call_sizes=True,
        )

        tokens = result["by_server"]["azure"]["estimated_result_tokens"]
        assert tokens["total"] == 0.0
        assert tokens["mean_result_tokens_per_call"] is None

    def test_builtin_tool_never_contributes_to_server_tokens(self) -> None:
        """Cost rollup is MCP-only, mirroring by_server/by_method's scope.

        ASSUMED SCOPE: a built-in tool's ``result_chars`` (even when
        measured) must not leak into any MCP server's
        ``estimated_result_tokens`` -- ``by_server``/``by_method`` are
        already MCP-only (only ``mcp__``-prefixed, normalisable names
        enter ``server_calls``/``server_methods``), and this suite
        requires the new cost fields to respect that same boundary
        rather than introduce a wider one.
        """
        result = compute_tool_usage(
            [
                (
                    "s1",
                    [
                        _use_measured("mcp__azure__storage", 400),
                        _use_measured("Read", 4000),
                    ],
                    [],
                )
            ],
            track_mcp_call_sizes=True,
        )

        tokens = result["by_server"]["azure"]["estimated_result_tokens"]
        assert tokens["total"] == 100.0
        assert tokens["mean_result_tokens_per_call"] == 100.0


class TestCostAttribution:
    """The ``cost_attribution`` block (plan §6b) and its three counters.

    This is the crux of Phase 2: distinguishing "no tool_result was
    ever found for this call" (``calls_without_result``) from "a
    tool_result was found but its content was excluded as unmeasurable"
    (``calls_with_excluded_content``). Phase 1's ``result_chars`` field
    cannot make this distinction on its own -- both cases render as
    ``None`` -- see the ``_use_excluded`` docstring above for the
    ``result_excluded: bool`` field this suite assumes as the fix.

    A conflated implementation (treating every ``result_chars is None``
    record as "without result", ignoring ``result_excluded``) would
    fail ``test_the_three_counters_are_distinct`` below: it would
    report ``calls_without_result=4`` / ``calls_with_excluded_content=0``
    instead of the correct 2/2 split. That is precisely the failure
    mode this test is written to catch.
    """

    def test_shape_matches_plan_exactly(self) -> None:
        result = compute_tool_usage(
            [("s1", [_use_measured("mcp__azure__storage", 400)], [])],
            track_mcp_call_sizes=True,
        )

        assert result["cost_attribution"] == {
            "method": "tool_result_payload_size",
            "is_proxy": True,
            "unit": "estimated_tokens",
            "basis": "len(tool_result content) / chars_per_token",
            "chars_per_token": 4.0,
            "excludes": ["tool_use.input arguments", "image content blocks"],
            "calls_with_result": 1,
            "calls_without_result": 0,
            "calls_with_excluded_content": 0,
        }

    def test_the_three_counters_are_distinct(self) -> None:
        """The crux test: missing vs excluded must not be conflated.

        Two calls of each kind -- measured, missing entirely, and found
        but excluded -- plus one measured built-in call.

        ASSUMED SCOPE: unlike ``by_server``/``by_method`` (which are
        MCP-only by construction -- a non-normalisable ``tool_name``
        never enters ``server_calls``), the plan does not explicitly
        state whether ``cost_attribution``'s three counters are
        MCP-only or corpus-wide. §6b presents ``cost_attribution`` as a
        top-level sibling of ``availability_signal``, which is
        corpus-level, not MCP-scoped -- so a corpus-wide reading is
        equally defensible. This suite pins **MCP-only** (the built-in
        ``Read`` call below must not count toward any of the three
        counters), for consistency with every other per-tool cost
        field in this phase. If the implementer disagrees, this is a
        named dispute to raise, not a silent deviation: the built-in
        call's presence in this fixture is deliberate, not incidental.
        """
        records = [
            _use_measured("mcp__azure__storage", 400),
            _use_measured("mcp__azure__storage", 800),
            _use("mcp__azure__acr"),
            _use("mcp__azure__acr"),
            _use_excluded("mcp__azure__acr"),
            _use_excluded("mcp__azure__acr"),
            _use_measured("Read", 4000),
        ]

        result = compute_tool_usage([("s1", records, [])], track_mcp_call_sizes=True)

        attribution = result["cost_attribution"]
        assert attribution["calls_with_result"] == 2
        assert attribution["calls_without_result"] == 2
        assert attribution["calls_with_excluded_content"] == 2

    def test_excluded_calls_do_not_count_as_measured_or_as_zero_cost(
        self,
    ) -> None:
        """An excluded call must render as unknown, never as a cheap 0.

        Guards the plan's explicit warning: "a zero here is a claim
        that the call was free, which for an image-returning call is
        the opposite of the truth."
        """
        result = compute_tool_usage(
            [
                (
                    "s1",
                    [
                        _use_measured("mcp__azure__storage", 400),
                        _use_excluded("mcp__azure__storage"),
                    ],
                    [],
                )
            ],
            track_mcp_call_sizes=True,
        )

        tokens = result["by_server"]["azure"]["estimated_result_tokens"]
        # Only the one measured call contributes: total 100, mean 100 --
        # not diluted to a mean of 50 by treating the excluded call as
        # a zero-cost data point.
        assert tokens["total"] == 100.0
        assert tokens["mean_result_tokens_per_call"] == 100.0
        assert result["cost_attribution"]["calls_with_result"] == 1
        assert result["cost_attribution"]["calls_with_excluded_content"] == 1
