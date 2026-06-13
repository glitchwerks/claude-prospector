"""Data classes for parsed Claude Code session data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """A single assistant message with token usage, attributed to an agent.

    Attributes:
        timestamp: When the assistant message was produced.
        model: Full model ID string (e.g. ``"claude-opus-4-7"``).
        agent_type: Leaf agent name (e.g. ``"general-purpose"``). Stored
            independently from ``agent_path``; maintaining the invariant
            ``agent_type == agent_path[-1]`` (when ``agent_path`` is
            non-empty) is the parser's responsibility at construction time.
        agent_path: Full ancestry tuple from root to leaf agent. Defaults
            to the empty tuple for records that pre-date nested attribution.
            Neither field is derived from the other.
        skill: Skill name invoked in this message, or ``None``.
        input_tokens: Prompt token count.
        output_tokens: Completion token count.
        cache_read_tokens: Tokens served from the prompt cache.
        cache_creation_tokens: Tokens written to the prompt cache.
    """

    timestamp: datetime
    model: str
    agent_type: str
    skill: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    agent_path: tuple[str, ...] = ()

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )

    @property
    def model_short(self) -> str:
        """Extract the model-tier name from the full model ID string.

        Uses substring matching so the classification is version-agnostic:
        ``claude-opus-4-7``, ``claude-opus-4-8``, ``claude-opus-5-0``, etc.
        all return ``"opus"`` because ``"opus"`` appears in the model ID.
        This avoids hardcoded version numbers and keeps working correctly
        after a model-version bump (issue #196).

        Returns:
            ``"opus"``, ``"sonnet"``, ``"haiku"``, or ``"fable"`` when the
            tier name is found as a substring of :attr:`model`.  Returns the
            full :attr:`model` string when no known tier name is present
            (e.g. a hypothetical future model ID that omits the tier name
            entirely).
        """
        for name in ("opus", "sonnet", "haiku", "fable"):
            if name in self.model:
                return name
        return self.model


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """A parsed session with all its messages (including subagent messages).

    Attributes:
        session_id: Unique session identifier (stem of the JSONL filename).
        project: Human-readable project leaf name, derived cwd-first.
            When the session's JSONL contains a ``cwd`` field the leaf
            directory (``Path(cwd).name``) is used; otherwise the last
            ``--``-separated segment of the encoded slug is used.
        project_path: Full path for the project.  When a ``cwd`` field
            is present this is the verbatim ``cwd`` value; otherwise it
            is the full decoded slug (see
            :func:`~claude_prospector.parser.decode_project_hash_full`).
            Empty string when neither is available.
        start_time: Timestamp of the earliest message in the session.
        root_agent: Agent-setting value for the root session thread.
        messages: All messages from this session and its subagents.
        subagent_types: Sorted, de-duplicated list of subagent type names
            encountered at any depth.
    """

    session_id: str
    project: str
    project_path: str
    start_time: datetime
    root_agent: str
    messages: list[MessageRecord]
    subagent_types: list[str]

    @property
    def total_tokens(self) -> int:
        return sum(m.total_tokens for m in self.messages)

    @property
    def duration_minutes(self) -> int:
        """Duration from first to last message timestamp, in minutes."""
        if len(self.messages) < 2:
            return 0
        timestamps = [m.timestamp for m in self.messages]
        delta = max(timestamps) - min(timestamps)
        return int(delta.total_seconds() / 60)


@dataclass(frozen=True, slots=True)
class SkillPassedEvent:
    """A skill reference found in an Agent dispatch prompt."""

    skill: str
    target_agent: str
    timestamp: datetime
    session_id: str


@dataclass(frozen=True, slots=True)
class SkillInvokedEvent:
    """An actual Skill tool invocation."""

    skill: str
    timestamp: datetime
    session_id: str
