"""Unit tests for per-token-type breakdowns in by_day and sessions.

Covers issue #165: add input_tokens, output_tokens, cache_creation_tokens,
cache_read_tokens (and message_count for by_day) to the aggregator output
shapes for by_day entries and sessions entries.
"""

from __future__ import annotations

from datetime import datetime, timezone

from claude_prospector.aggregator import aggregate
from claude_prospector.models import MessageRecord, SessionRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(
    *,
    input_t: int = 100,
    output_t: int = 50,
    cache_read: int = 0,
    cache_create: int = 0,
    model: str = "claude-opus-4-6",
    agent: str = "general-purpose",
    skill: str | None = None,
    ts: datetime | None = None,
) -> MessageRecord:
    """Build a ``MessageRecord`` with explicit per-token fields.

    Args:
        input_t: Input token count.
        output_t: Output token count.
        cache_read: Cache read token count.
        cache_create: Cache creation token count.
        model: Full model ID string.
        agent: Agent type / leaf name.
        skill: Optional skill name.
        ts: Timestamp; defaults to 2026-04-09 12:00 UTC.

    Returns:
        A ``MessageRecord`` instance.
    """
    return MessageRecord(
        timestamp=ts or datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc),
        model=model,
        agent_type=agent,
        agent_path=(agent,),
        skill=skill,
        input_tokens=input_t,
        output_tokens=output_t,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_create,
    )


def _session(
    messages: list[MessageRecord],
    session_id: str = "s1",
    project: str = "proj",
    root_agent: str = "general-purpose",
) -> SessionRecord:
    """Build a ``SessionRecord`` from a list of messages.

    Args:
        messages: The messages belonging to the session.
        session_id: Unique session identifier.
        project: Project name.
        root_agent: Root agent type for the session.

    Returns:
        A ``SessionRecord`` instance.
    """
    start = (
        min(m.timestamp for m in messages)
        if messages
        else datetime(2026, 4, 9, tzinfo=timezone.utc)
    )
    return SessionRecord(
        session_id=session_id,
        project=project,
        project_path="",
        start_time=start,
        root_agent=root_agent,
        messages=messages,
        subagent_types=[],
    )


# ---------------------------------------------------------------------------
# by_day per-token fields
# ---------------------------------------------------------------------------


class TestByDayPerTokenFields:
    """by_day entries must carry all four per-token fields plus message_count."""

    def test_single_message_session_by_day_fields_present(self) -> None:
        """A single-message session populates all per-token fields in by_day."""
        sessions = [_session([_msg(input_t=10, output_t=5)])]
        result = aggregate(sessions)

        day = "2026-04-09"
        assert day in result.by_day
        entry = result.by_day[day]
        assert "input_tokens" in entry
        assert "output_tokens" in entry
        assert "cache_creation_tokens" in entry
        assert "cache_read_tokens" in entry
        assert "message_count" in entry

    def test_single_message_session_by_day_values(self) -> None:
        """Per-token fields in by_day equal the single message's values."""
        sessions = [
            _session([_msg(input_t=10, output_t=5, cache_read=3, cache_create=2)])
        ]
        result = aggregate(sessions)
        entry = result.by_day["2026-04-09"]
        assert entry["input_tokens"] == 10
        assert entry["output_tokens"] == 5
        assert entry["cache_read_tokens"] == 3
        assert entry["cache_creation_tokens"] == 2
        assert entry["message_count"] == 1

    def test_multi_message_same_day_by_day_sums_correctly(self) -> None:
        """Multiple messages on the same day are summed per token type."""
        ts = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 4, 9, 14, 0, 0, tzinfo=timezone.utc)
        sessions = [
            _session(
                [
                    _msg(input_t=10, output_t=5, cache_read=1, cache_create=2, ts=ts),
                    _msg(input_t=20, output_t=10, cache_read=3, cache_create=4, ts=ts2),
                ]
            )
        ]
        result = aggregate(sessions)
        entry = result.by_day["2026-04-09"]
        assert entry["input_tokens"] == 30
        assert entry["output_tokens"] == 15
        assert entry["cache_read_tokens"] == 4
        assert entry["cache_creation_tokens"] == 6
        assert entry["message_count"] == 2

    def test_multi_day_per_token_fields_segregated(self) -> None:
        """Messages on different days have independent per-token sums."""
        day1_ts = datetime(2026, 4, 8, 10, 0, 0, tzinfo=timezone.utc)
        day2_ts = datetime(2026, 4, 9, 14, 0, 0, tzinfo=timezone.utc)
        sessions = [
            _session(
                [
                    _msg(input_t=100, output_t=50, ts=day1_ts),
                    _msg(input_t=200, output_t=100, ts=day2_ts),
                ]
            )
        ]
        result = aggregate(sessions)
        assert result.by_day["2026-04-08"]["input_tokens"] == 100
        assert result.by_day["2026-04-08"]["output_tokens"] == 50
        assert result.by_day["2026-04-09"]["input_tokens"] == 200
        assert result.by_day["2026-04-09"]["output_tokens"] == 100

    def test_by_day_new_fields_default_zero_when_absent(self) -> None:
        """Cache fields default to 0 when a message has no cache tokens."""
        sessions = [
            _session([_msg(input_t=100, output_t=50, cache_read=0, cache_create=0)])
        ]
        result = aggregate(sessions)
        entry = result.by_day["2026-04-09"]
        assert entry["cache_read_tokens"] == 0
        assert entry["cache_creation_tokens"] == 0

    def test_total_tokens_invariant_equals_sum_of_parts_per_day(self) -> None:
        """by_day total_tokens == input + output + cache_creation + cache_read."""
        ts = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
        sessions = [
            _session(
                [
                    _msg(
                        input_t=100, output_t=50, cache_read=10, cache_create=5, ts=ts
                    ),
                    _msg(
                        input_t=200, output_t=80, cache_read=0, cache_create=20, ts=ts
                    ),
                ]
            )
        ]
        result = aggregate(sessions)
        entry = result.by_day["2026-04-09"]
        expected_total = (
            entry["input_tokens"]
            + entry["output_tokens"]
            + entry["cache_read_tokens"]
            + entry["cache_creation_tokens"]
        )
        assert entry["total_tokens"] == expected_total

    def test_sum_of_by_day_total_tokens_equals_result_total_tokens(self) -> None:
        """sum(by_day[*].total_tokens) == result.total_tokens."""
        day1_ts = datetime(2026, 4, 8, 10, 0, 0, tzinfo=timezone.utc)
        day2_ts = datetime(2026, 4, 9, 14, 0, 0, tzinfo=timezone.utc)
        sessions = [
            _session(
                [
                    _msg(
                        input_t=100,
                        output_t=50,
                        cache_read=5,
                        cache_create=10,
                        ts=day1_ts,
                    ),
                    _msg(input_t=200, output_t=100, ts=day2_ts),
                ]
            )
        ]
        result = aggregate(sessions)
        day_total = sum(v["total_tokens"] for v in result.by_day.values())
        assert day_total == result.total_tokens


# ---------------------------------------------------------------------------
# sessions[*] per-token fields
# ---------------------------------------------------------------------------


class TestSessionsPerTokenFields:
    """sessions entries must carry all four per-token fields."""

    def test_single_message_session_token_fields_present(self) -> None:
        """A single-message session summary carries all per-token fields."""
        sessions = [_session([_msg(input_t=10, output_t=5)])]
        result = aggregate(sessions)

        assert len(result.sessions) == 1
        s = result.sessions[0]
        assert "input_tokens" in s
        assert "output_tokens" in s
        assert "cache_creation_tokens" in s
        assert "cache_read_tokens" in s

    def test_single_message_session_token_values(self) -> None:
        """Per-token fields in the session summary equal the message's values."""
        sessions = [
            _session([_msg(input_t=10, output_t=5, cache_read=3, cache_create=2)])
        ]
        result = aggregate(sessions)
        s = result.sessions[0]
        assert s["input_tokens"] == 10
        assert s["output_tokens"] == 5
        assert s["cache_read_tokens"] == 3
        assert s["cache_creation_tokens"] == 2

    def test_multi_message_session_token_fields_sum(self) -> None:
        """Multi-message session: per-token fields are summed over all messages."""
        sessions = [
            _session(
                [
                    _msg(input_t=10, output_t=5, cache_read=1, cache_create=2),
                    _msg(input_t=20, output_t=10, cache_read=3, cache_create=4),
                ]
            )
        ]
        result = aggregate(sessions)
        s = result.sessions[0]
        assert s["input_tokens"] == 30
        assert s["output_tokens"] == 15
        assert s["cache_read_tokens"] == 4
        assert s["cache_creation_tokens"] == 6

    def test_session_new_fields_default_zero_when_no_cache(self) -> None:
        """Cache token fields default to 0 when messages have no cache tokens."""
        sessions = [
            _session([_msg(input_t=100, output_t=50, cache_read=0, cache_create=0)])
        ]
        result = aggregate(sessions)
        s = result.sessions[0]
        assert s["cache_read_tokens"] == 0
        assert s["cache_creation_tokens"] == 0

    def test_session_total_tokens_unchanged_by_new_fields(self) -> None:
        """Adding per-token fields must not change existing total_tokens value."""
        sessions = [
            _session([_msg(input_t=100, output_t=50, cache_read=10, cache_create=5)])
        ]
        result = aggregate(sessions)
        s = result.sessions[0]
        # total_tokens = input + output + cache_read + cache_create = 165
        assert s["total_tokens"] == 165
        # Per-token fields must be consistent with total_tokens
        parts_sum = (
            s["input_tokens"]
            + s["output_tokens"]
            + s["cache_read_tokens"]
            + s["cache_creation_tokens"]
        )
        assert parts_sum == s["total_tokens"]

    def test_multi_session_each_has_independent_token_counts(self) -> None:
        """Multiple sessions each track their own per-token counts independently."""
        sessions = [
            _session(
                [_msg(input_t=100, output_t=50)],
                session_id="s1",
                project="proj-a",
            ),
            _session(
                [_msg(input_t=200, output_t=100, cache_read=20)],
                session_id="s2",
                project="proj-b",
            ),
        ]
        result = aggregate(sessions)
        # Sort by session_id for determinism (sessions are sorted by start_time desc)
        by_id = {s["session_id"]: s for s in result.sessions}
        assert by_id["s1"]["input_tokens"] == 100
        assert by_id["s1"]["cache_read_tokens"] == 0
        assert by_id["s2"]["input_tokens"] == 200
        assert by_id["s2"]["cache_read_tokens"] == 20

    def test_existing_fields_unchanged_sessions(self) -> None:
        """Adding new fields must not alter total_tokens, model_split, message_count."""
        sessions = [
            _session(
                [
                    _msg(
                        input_t=100,
                        output_t=50,
                        model="claude-opus-4-6",
                    ),
                    _msg(
                        input_t=200,
                        output_t=100,
                        model="claude-sonnet-4-6",
                    ),
                ]
            )
        ]
        result = aggregate(sessions)
        s = result.sessions[0]
        assert s["total_tokens"] == 450
        assert s["message_count"] == 2
        assert s["model_split"] == {"opus": 150, "sonnet": 300}

    def test_existing_fields_unchanged_by_day(self) -> None:
        """Adding new fields must not alter by_day total_tokens or by_model."""
        sessions = [
            _session(
                [
                    _msg(input_t=100, output_t=50, model="claude-opus-4-6"),
                    _msg(input_t=200, output_t=100, model="claude-sonnet-4-6"),
                ]
            )
        ]
        result = aggregate(sessions)
        entry = result.by_day["2026-04-09"]
        assert entry["total_tokens"] == 450
        assert entry["by_model"] == {"opus": 150, "sonnet": 300}
