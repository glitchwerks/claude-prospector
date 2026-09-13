"""Regression tests for the additive session analytics payload."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from claude_prospector.aggregator import AGENT_PATH_SEPARATOR, aggregate
from claude_prospector.models import (
    CommandInvocationRecord,
    MessageRecord,
    SessionMetadataObservation,
    SessionRecord,
    SkillInvocationRecord,
)


def _effort_session() -> SessionRecord:
    """Build a deterministic multi-agent session with activity facts."""
    start = datetime(2026, 9, 13, 10, tzinfo=timezone.utc)
    messages = [
        MessageRecord(
            timestamp=start,
            model="claude-sonnet-5",
            agent_type="main",
            skill="python",
            input_tokens=10,
            output_tokens=20,
            cache_read_tokens=30,
            cache_creation_tokens=40,
            agent_path=("main",),
            effort="high",
        ),
        MessageRecord(
            timestamp=start + timedelta(minutes=1),
            model="claude-opus-5",
            agent_type="worker",
            skill=None,
            input_tokens=1,
            output_tokens=2,
            cache_read_tokens=3,
            cache_creation_tokens=4,
            agent_path=("main", "worker"),
            effort=None,
        ),
    ]
    return SessionRecord(
        session_id="effort-session",
        project="project",
        project_path="/project",
        start_time=start,
        root_agent="main",
        messages=messages,
        subagent_types=["worker"],
        agent_paths=[("main",), ("main", "worker")],
        commands=[CommandInvocationRecord(name="/compact", timestamp=start)],
        skill_invocations=[
            SkillInvocationRecord(
                skill="python",
                timestamp=start,
                agent_path=("main",),
                tool_use_id="tool-python",
            )
        ],
        metadata_observations=[
            SessionMetadataObservation(
                name="git_branch",
                value="main",
                timestamp=start,
                agent_path=("main",),
            )
        ],
    )


def test_session_detail_payload_is_exact_and_additive() -> None:
    """Expose complete deterministic activity alongside legacy session data."""
    session = aggregate([_effort_session()]).sessions[0]

    assert session["agent_activity"] == [
        {
            "timestamp": "2026-09-13T10:00:00+00:00",
            "agent": "main",
            "agent_path": ["main"],
            "model": "sonnet",
            "model_full": "claude-sonnet-5",
            "effort": "high",
            "effort_key": "high",
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_tokens": 30,
            "cache_creation_tokens": 40,
            "total_tokens": 100,
        },
        {
            "timestamp": "2026-09-13T10:01:00+00:00",
            "agent": f"main{AGENT_PATH_SEPARATOR}worker",
            "agent_path": ["main", "worker"],
            "model": "opus",
            "model_full": "claude-opus-5",
            "effort": None,
            "effort_key": "unknown",
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_read_tokens": 3,
            "cache_creation_tokens": 4,
            "total_tokens": 10,
        },
    ]
    assert session["end_time"] == "2026-09-13T10:01:00+00:00"
    assert session["duration_seconds"] == 60
    assert session["agent_paths"] == [["main"], ["main", "worker"]]
    assert session["effort_split"] == {"high": 100, "unknown": 10}
    assert session["skill_activity"] == [
        {
            "timestamp": "2026-09-13T10:00:00+00:00",
            "agent": "main",
            "agent_path": ["main"],
            "skill": "python",
        }
    ]
    assert session["command_activity"] == [
        {
            "timestamp": "2026-09-13T10:00:00+00:00",
            "agent": "main",
            "agent_path": ["main"],
            "name": "/compact",
        }
    ]
    assert session["session_facts"] == {
        "metadata": [
            {
                "name": "git_branch",
                "value": "main",
                "first_seen": "2026-09-13T10:00:00+00:00",
                "agent_paths": [["main"]],
            }
        ],
        "effort_conflicts": 0,
    }
    assert session["mcp_collection"] == {
        "calls": "not_collected",
        "result_sizes": "not_collected",
    }
    assert session["mcp_activity"] is None
    assert {"agent_tokens", "agent_stats", "model_split", "duration_minutes"} <= set(
        session
    )


def test_response_dimensions_reconcile_to_session_total() -> None:
    """Keep response dimensions and effort splits aligned with session totals."""
    session = aggregate([_effort_session()]).sessions[0]
    responses = session["agent_activity"]

    assert sum(row["total_tokens"] for row in responses) == session["total_tokens"]
    assert sum(row["input_tokens"] for row in responses) == session["input_tokens"]
    assert sum(row["output_tokens"] for row in responses) == session["output_tokens"]
    assert (
        sum(row["cache_read_tokens"] for row in responses)
        == session["cache_read_tokens"]
    )
    assert (
        sum(row["cache_creation_tokens"] for row in responses)
        == session["cache_creation_tokens"]
    )
    assert sum(session["effort_split"].values()) == session["total_tokens"]


def test_session_activity_respects_the_cli_time_window() -> None:
    """Filter response, Skill, and Command activity by their timestamps."""
    start = datetime(2026, 9, 13, 10, tzinfo=timezone.utc)
    session = _effort_session()
    windowed = replace(
        session,
        commands=session.commands
        + [
            CommandInvocationRecord(
                name="/later",
                timestamp=start + timedelta(minutes=1),
            )
        ],
        skill_invocations=session.skill_invocations
        + [
            SkillInvocationRecord(
                skill="later-skill",
                timestamp=start + timedelta(minutes=1),
                agent_path=("main", "worker"),
                tool_use_id="tool-later",
            )
        ],
    )

    summary = aggregate(
        [windowed],
        from_date=start + timedelta(minutes=1),
        to_date=start + timedelta(minutes=2),
    ).sessions[0]

    assert [row["timestamp"] for row in summary["agent_activity"]] == [
        "2026-09-13T10:01:00+00:00"
    ]
    assert summary["skill_activity"] == [
        {
            "timestamp": "2026-09-13T10:01:00+00:00",
            "agent": f"main{AGENT_PATH_SEPARATOR}worker",
            "agent_path": ["main", "worker"],
            "skill": "later-skill",
        }
    ]
    assert summary["command_activity"] == [
        {
            "timestamp": "2026-09-13T10:01:00+00:00",
            "agent": "main",
            "agent_path": ["main"],
            "name": "/later",
        }
    ]
