"""Collect tool invocations and MCP availability from agent transcripts.

This is the second visitor over :mod:`claude_prospector.transcript_walker`
(the first being :mod:`claude_prospector.parser`, which produces token
records). It reads raw counts only — no filtering, no normalisation, no
aggregation. Those belong to a downstream aggregator.

Privacy: only tool *names* and *ids* are read. ``tool_use.input`` is never
touched, because it carries file paths and shell commands.
"""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from claude_prospector.mcp_names import normalize_mcp_tool_name
from claude_prospector.models import AgentAvailability, SessionRecord, ToolUseRecord
from claude_prospector.transcript_walker import AgentTranscript, walk_session

_DEFERRED_TOOLS_DELTA = "deferred_tools_delta"
_MCP_INSTRUCTIONS_DELTA = "mcp_instructions_delta"
_AVAILABILITY_ATTACHMENT_TYPES = frozenset(
    {_DEFERRED_TOOLS_DELTA, _MCP_INSTRUCTIONS_DELTA}
)


def _iter_entries(jsonl_path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSONL entries from *jsonl_path*, skipping bad lines.

    Args:
        jsonl_path: Path to a transcript JSONL file.

    Yields:
        One ``dict`` per parseable line, in file order. Unreadable files
        yield nothing rather than raising.
    """
    try:
        handle = open(jsonl_path, encoding="utf-8")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                yield entry


def _instruction_server_name(raw: str) -> str:
    """Normalise an ``mcp_instructions_delta`` server name.

    Plugin-scoped servers appear as ``plugin:<plugin>:<server>``, e.g.
    ``plugin:microsoft-docs:microsoft-learn``. The matching tool names in
    ``deferred_tools_delta`` normalise to ``microsoft-learn.<method>``, so
    stripping the prefix makes the two sources agree.

    Args:
        raw: Server name from ``addedNames`` / ``removedNames``.

    Returns:
        The bare server name.
    """
    if raw.startswith("plugin:"):
        return raw.rsplit(":", 1)[-1]
    return raw


def collect_unit(
    unit: AgentTranscript,
) -> tuple[list[ToolUseRecord], AgentAvailability]:
    """Collect tool calls and MCP availability from one agent transcript.

    Single forward scan over the transcript's entries, merging what were
    previously two independent passes (:func:`collect_tool_uses` and
    :func:`collect_availability`): one branch per ``entry["type"]``, so the
    file is read once instead of twice.

    ``assistant`` branch — reads every ``assistant`` entry, deliberately
    without the ``message.id`` de-duplication that
    :mod:`claude_prospector.parser` applies to token usage. A multi-block
    assistant message is written as consecutive JSONL lines sharing one
    ``message.id``, each carrying a distinct ``tool_use`` block;
    de-duplicating by ``message.id`` here would discard every parallel tool
    call but the first. De-duplication is by ``tool_use.id`` only, scoped to
    this file. Nothing is skipped and nothing is collapsed: built-in tools
    count the same as MCP tools, and ten consecutive identical calls count
    as ten.

    ``attachment`` branch — applies ``addedNames`` / ``removedNames`` deltas
    in file order across both signal types, then unions the results: a
    server counts as available if **either** source names it. The two
    sources have complementary blind spots (``mcp_instructions_delta``
    misses servers that ship no instructions; ``deferred_tools_delta``
    misses eagerly-loaded tools), so a server named by only one is expected,
    not contradictory.

    Args:
        unit: One agent transcript from the walker.

    Returns:
        A 2-tuple ``(tool_uses, availability)``. ``tool_uses`` is empty
        when the file is missing or unreadable. ``availability`` is always
        returned — even for a file with no ``attachment`` entry at all, in
        which case its ``signal_present`` is False and callers must report
        availability as unknown rather than zero.
    """
    records: list[ToolUseRecord] = []
    seen_ids: set[str] = set()
    observed_sources: set[str] = set()
    deferred_tools: set[str] = set()
    instruction_servers: set[str] = set()

    for entry in _iter_entries(unit.jsonl_path):
        entry_type = entry.get("type")
        if entry_type == "assistant":
            content = entry.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_use_id = block.get("id") or ""
                if tool_use_id:
                    if tool_use_id in seen_ids:
                        continue
                    seen_ids.add(tool_use_id)
                records.append(
                    ToolUseRecord(
                        tool_name=block.get("name", ""),
                        tool_use_id=tool_use_id,
                        agent_type=unit.agent_type,
                        agent_path=unit.agent_path,
                    )
                )
        elif entry_type == "attachment":
            attachment = entry.get("attachment")
            if not isinstance(attachment, dict):
                continue
            attachment_type = attachment.get("type")
            if attachment_type not in _AVAILABILITY_ATTACHMENT_TYPES:
                continue

            observed_sources.add(attachment_type)
            target = (
                deferred_tools
                if attachment_type == _DEFERRED_TOOLS_DELTA
                else instruction_servers
            )
            for name in attachment.get("addedNames") or []:
                if isinstance(name, str):
                    target.add(name)
            for name in attachment.get("removedNames") or []:
                if isinstance(name, str):
                    target.discard(name)

    sources: dict[str, set[str]] = {}
    for raw_tool in deferred_tools:
        normalised = normalize_mcp_tool_name(raw_tool)
        if normalised is None:
            continue
        server = normalised.split(".", 1)[0]
        sources.setdefault(server, set()).add(_DEFERRED_TOOLS_DELTA)
    for raw_server in instruction_servers:
        server = _instruction_server_name(raw_server)
        if server:
            sources.setdefault(server, set()).add(_MCP_INSTRUCTIONS_DELTA)

    availability = AgentAvailability(
        agent_path=unit.agent_path,
        observed_sources=frozenset(observed_sources),
        server_sources={k: frozenset(v) for k, v in sources.items()},
    )
    return records, availability


def collect_tool_uses(unit: AgentTranscript) -> list[ToolUseRecord]:
    """Collect every tool invocation in one agent's transcript.

    Thin wrapper over :func:`collect_unit`, kept for existing callers.

    Args:
        unit: One agent transcript from the walker.

    Returns:
        Records in file order. Empty when the file is missing or
        unreadable.
    """
    tool_uses, _ = collect_unit(unit)
    return tool_uses


def collect_availability(unit: AgentTranscript) -> AgentAvailability:
    """Determine which MCP servers were available to one agent.

    Thin wrapper over :func:`collect_unit`, kept for existing callers.

    Args:
        unit: One agent transcript from the walker.

    Returns:
        An :class:`~claude_prospector.models.AgentAvailability`. When no
        delta entry appears at all, ``signal_present`` is False and
        callers must report availability as unknown rather than zero.
    """
    _, availability = collect_unit(unit)
    return availability


def collect_session(
    session_jsonl: Path,
    root_agent: str,
) -> tuple[list[ToolUseRecord], list[AgentAvailability]]:
    """Collect tool calls and availability for a whole session tree.

    Args:
        session_jsonl: Path to the root session JSONL file.
        root_agent: Raw agent-setting value for the root thread.

    Returns:
        A 2-tuple of ``(tool_uses, availabilities)``. ``availabilities``
        has one entry per agent transcript, so a caller can union them
        for a session-level view or filter to one agent.
    """
    transcripts, _ = walk_session(session_jsonl, root_agent)
    tool_uses: list[ToolUseRecord] = []
    availabilities: list[AgentAvailability] = []
    for unit in transcripts:
        unit_tool_uses, unit_availability = collect_unit(unit)
        tool_uses.extend(unit_tool_uses)
        availabilities.append(unit_availability)
    return tool_uses, availabilities


def _matches_server(tool_name: str, wanted: str) -> bool:
    """Return True when *tool_name*'s normalized server equals *wanted*.

    Unlike the raw ``--tool`` glob filter, ``--server`` must match the
    server component of an MCP tool name exactly (after normalization),
    not as an fnmatch substring/prefix. A naive
    ``f"mcp__*{wanted}__*"`` pattern lets a leading ``*`` swallow a
    prefix (e.g. ``--server azure`` would wrongly match
    ``mcp__myazure__storage``).

    Args:
        tool_name: Raw tool name from the transcript.
        wanted: The exact server name requested via ``--server``.

    Returns:
        True if *tool_name* is a well-formed MCP tool name whose server
        component equals *wanted* exactly.
    """
    normalized = normalize_mcp_tool_name(tool_name)
    if normalized is None:
        return False
    server, _, _method = normalized.partition(".")
    return server == wanted


def _matches_agent(agent_path: tuple[str, ...], wanted: str | None) -> bool:
    """Return True when *agent_path* contains *wanted* (or no filter is set).

    Args:
        agent_path: Full root-to-leaf ancestry tuple for an agent.
        wanted: Agent name to match against any segment of the path, or
            None to disable the filter.

    Returns:
        True if the filter is disabled or *wanted* appears in *agent_path*.
    """
    return wanted is None or wanted in agent_path


def collect_per_session(
    sessions: list[SessionRecord],
    data_dir: Path,
    *,
    agent: str | None = None,
    tool: str | None = None,
    server: str | None = None,
) -> tuple[list[tuple[str, list[ToolUseRecord], list[AgentAvailability]]], int]:
    """Collect tool-use and availability records for a list of sessions.

    Callers own session selection: *sessions* must already be filtered to
    exactly the sessions to collect (e.g. by ``--repo`` and a date
    window). This function applies no time filtering and no ``--repo``
    filtering of its own — only the record-level ``agent``/``tool``/
    ``server`` filters below.

    Args:
        sessions: Already-selected sessions to collect. ``SessionRecord``
            carries no JSONL path, so each session's transcript is
            located by globbing ``{data_dir}/projects/*/{session_id}.jsonl``
            (session ids are UUIDs, so at most one file matches).
        data_dir: Claude data directory containing the ``projects/``
            tree.
        agent: When set, keep only records whose ``agent_path`` contains
            this value (matched via :func:`_matches_agent`). Applies to
            both ``tool_uses`` and ``availabilities``.
        tool: When set, keep only tool_uses whose raw ``tool_name``
            matches this glob pattern (via ``fnmatch``). Does not filter
            ``availabilities``. Mutually exclusive with *server* by
            caller-side contract: when both are set, *tool* silently
            takes precedence (``elif``, not two independent filters) and
            *server* is ignored — this is not validated here.
        server: When set and *tool* is not, keep only tool_uses whose
            normalized server equals this value (via
            :func:`_matches_server`). Does not filter ``availabilities``.

    Returns:
        A 2-tuple ``(per_session, skipped)``. ``per_session`` is the
        exact shape :func:`~claude_prospector.aggregator.compute_tool_usage`
        consumes: one ``(session_id, tool_uses, availabilities)`` tuple
        per session whose transcript was found and readable. ``skipped``
        counts sessions whose transcript was missing or raised
        ``OSError``.
    """
    per_session: list[tuple[str, list[ToolUseRecord], list[AgentAvailability]]] = []
    skipped = 0

    for session in sessions:
        matches = list((data_dir / "projects").glob(f"*/{session.session_id}.jsonl"))
        if not matches:
            skipped += 1
            continue
        jsonl_path = matches[0]

        try:
            tool_uses, availabilities = collect_session(jsonl_path, session.root_agent)
        except OSError:
            skipped += 1
            continue

        if agent is not None:
            tool_uses = [r for r in tool_uses if _matches_agent(r.agent_path, agent)]
            availabilities = [
                a for a in availabilities if _matches_agent(a.agent_path, agent)
            ]
        if tool is not None:
            tool_uses = [r for r in tool_uses if fnmatch.fnmatch(r.tool_name, tool)]
        elif server is not None:
            tool_uses = [r for r in tool_uses if _matches_server(r.tool_name, server)]

        per_session.append((session.session_id, tool_uses, availabilities))

    return per_session, skipped
