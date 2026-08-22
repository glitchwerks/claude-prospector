"""Collect tool invocations and MCP availability from agent transcripts.

This is the second visitor over :mod:`claude_prospector.transcript_walker`
(the first being :mod:`claude_prospector.parser`, which produces token
records). It reads raw counts only — no filtering, no normalisation, no
aggregation. Those belong to a downstream aggregator.

Privacy: only tool *names* and *ids* are read. ``tool_use.input`` is never
touched, because it carries file paths and shell commands.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from claude_prospector.mcp_names import normalize_mcp_tool_name
from claude_prospector.models import AgentAvailability, ToolUseRecord
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


def collect_tool_uses(unit: AgentTranscript) -> list[ToolUseRecord]:
    """Collect every tool invocation in one agent's transcript.

    Reads every ``assistant`` entry — deliberately without the
    ``message.id`` de-duplication that :mod:`claude_prospector.parser`
    applies to token usage. A multi-block assistant message is written as
    consecutive JSONL lines sharing one ``message.id``, each carrying a
    distinct ``tool_use`` block; de-duplicating by ``message.id`` here would
    discard every parallel tool call but the first. De-duplication is by
    ``tool_use.id`` only.

    Nothing is skipped and nothing is collapsed: built-in tools count the
    same as MCP tools, and ten consecutive identical calls count as ten.

    Args:
        unit: One agent transcript from the walker.

    Returns:
        Records in file order. Empty when the file is missing or
        unreadable.
    """
    records: list[ToolUseRecord] = []
    seen_ids: set[str] = set()

    for entry in _iter_entries(unit.jsonl_path):
        if entry.get("type") != "assistant":
            continue
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
    return records


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


def collect_availability(unit: AgentTranscript) -> AgentAvailability:
    """Determine which MCP servers were available to one agent.

    Applies ``addedNames`` / ``removedNames`` deltas in file order across
    both signal types, then unions the results: a server counts as
    available if **either** source names it. The two sources have
    complementary blind spots (``mcp_instructions_delta`` misses servers
    that ship no instructions; ``deferred_tools_delta`` misses
    eagerly-loaded tools), so a server named by only one is expected, not
    contradictory.

    Args:
        unit: One agent transcript from the walker.

    Returns:
        An :class:`~claude_prospector.models.AgentAvailability`. When no
        delta entry appears at all, ``signal_present`` is False and
        callers must report availability as unknown rather than zero.
    """
    observed_sources: set[str] = set()
    deferred_tools: set[str] = set()
    instruction_servers: set[str] = set()

    for entry in _iter_entries(unit.jsonl_path):
        if entry.get("type") != "attachment":
            continue
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

    return AgentAvailability(
        agent_path=unit.agent_path,
        observed_sources=frozenset(observed_sources),
        server_sources={k: frozenset(v) for k, v in sources.items()},
    )


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
        tool_uses.extend(collect_tool_uses(unit))
        availabilities.append(collect_availability(unit))
    return tool_uses, availabilities
