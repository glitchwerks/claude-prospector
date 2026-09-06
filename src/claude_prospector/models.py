"""Data classes for parsed Claude Code session data."""

from __future__ import annotations

from dataclasses import dataclass, field
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
class CommandInvocationRecord:
    """A manual slash-command invocation from an external user entry.

    Attributes:
        name: Literal command name, including its leading slash.
        timestamp: When the user invoked the command.
    """

    name: str
    timestamp: datetime


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
        commands: Manual slash-command invocations. Records retain only the
            command name and timestamp, never arguments or prompt content.
    """

    session_id: str
    project: str
    project_path: str
    start_time: datetime
    root_agent: str
    messages: list[MessageRecord]
    subagent_types: list[str]
    commands: list[CommandInvocationRecord] = field(default_factory=list)

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


@dataclass(frozen=True, slots=True)
class ToolUseRecord:
    """A single tool invocation, attributed to the agent that made it.

    Attributes:
        tool_name: Raw tool name as it appears in the transcript, e.g.
            ``"Read"`` or ``"mcp__azure__storage"``. Never normalised here —
            normalisation is the aggregator's job.
        tool_use_id: The ``toolu_...`` block id. Empty string when the
            transcript omitted it.
        agent_type: Sanitized leaf agent name that issued the call.
        agent_path: Full root-to-leaf ancestry tuple for that agent.
        result_chars: Character length of this call's ``tool_result``
            payload (issue #262, D-1=M4), or ``None`` when unknown --
            either because size tracking was not opted into (the
            default), no matching result was found in the transcript, or
            the result contained an unmeasurable block (e.g. an image).
            Distinct from ``0``, which means a result was found and it
            was empty. See :mod:`claude_prospector.tool_collection` for
            how this is computed and gated.
        result_excluded: True when a ``tool_result`` was located for this
            call but its content was excluded as unmeasurable (e.g. an
            image block), as opposed to no ``tool_result`` ever being
            found. Distinguishes the two ``result_chars is None`` cases
            that would otherwise be conflated. Always False when
            ``result_chars`` holds a measured value.
    """

    tool_name: str
    tool_use_id: str
    agent_type: str
    agent_path: tuple[str, ...]
    result_chars: int | None = None
    result_excluded: bool = False


@dataclass(frozen=True, slots=True)
class AgentAvailability:
    """Which MCP servers were available to one agent, and how we know.

    Attributes:
        agent_path: Full root-to-leaf ancestry tuple for the agent.
        observed_sources: Attachment types that appeared in this agent's
            transcript (``"deferred_tools_delta"`` and/or
            ``"mcp_instructions_delta"``). Empty means the availability
            signal was absent entirely. A delta naming only built-in tools
            still lands here, which is why this is tracked separately from
            ``server_sources``.
        server_sources: Maps server name to the set of attachment types
            that confirmed it. Empty with a non-empty ``observed_sources``
            means "we could see the inventory and it named no MCP server".
    """

    agent_path: tuple[str, ...]
    observed_sources: frozenset[str]
    server_sources: dict[str, frozenset[str]]

    @property
    def signal_present(self) -> bool:
        """True when this transcript carried any availability delta.

        When False, ``server_sources`` is empty because the signal was
        absent — NOT because no servers were available. Consumers must
        render that case as ``null``, never ``0``.
        """
        return bool(self.observed_sources)
