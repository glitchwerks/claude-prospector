"""Walk a Claude Code session's transcript tree, one unit per agent.

This module owns the ``subagents/`` recursion, ``agent_path`` construction,
depth cap, and symlink-cycle defense that were previously private to
:mod:`claude_prospector.parser`.  Consumers drive the walker with their own
visitor: :mod:`claude_prospector.parser` turns each unit into
``MessageRecord`` objects, :mod:`claude_prospector.tool_collection` turns the
same units into tool-call and MCP-availability records.

The walker performs **no** parsing of message content — it only locates the
JSONL files and attributes each to an agent path.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

from claude_prospector.constants import (
    AGENT_PATH_SEPARATOR as _PATH_SEPARATOR,
    SANITIZED_SEPARATOR_REPLACEMENT as _SANITIZED_SEPARATOR_REPLACEMENT,
)

#: Maximum length of an ``agent_path`` tuple before the walk stops descending.
MAX_AGENT_PATH_LENGTH = 10


@dataclass(frozen=True, slots=True)
class AgentTranscript:
    """One agent's JSONL transcript, with its position in the agent tree.

    Attributes:
        jsonl_path: Path to the JSONL file for this agent. Guaranteed to
            exist at the time the walk produced it.
        agent_type: Sanitized leaf agent name.
        agent_path: Full ancestry tuple from root to this agent. Always
            non-empty; ``agent_path[-1] == agent_type``.
    """

    jsonl_path: Path
    agent_type: str
    agent_path: tuple[str, ...]


def sanitize_agent_name(name: str) -> str:
    """Replace path-separator characters in an agent name with U+FE56.

    The path separator ``→`` (U+2192) must not appear in any segment of an
    ``agent_path`` tuple; collisions are sanitized to ``﹖`` (U+FE56 SMALL
    QUESTION MARK) and a ``UserWarning`` is emitted so callers are alerted.

    Args:
        name: Raw agent name as read from ``*.meta.json``.

    Returns:
        Sanitized agent name with all ``→`` replaced by ``﹖``.
    """
    if _PATH_SEPARATOR in name:
        sanitized = name.replace(_PATH_SEPARATOR, _SANITIZED_SEPARATOR_REPLACEMENT)
        warnings.warn(
            f"Agent name contains path separator; sanitized: {name!r} -> {sanitized!r}",
            UserWarning,
            stacklevel=2,
        )
        return sanitized
    return name


def walk_session(
    session_jsonl: Path,
    root_agent: str,
) -> tuple[list[AgentTranscript], list[str]]:
    """Walk a session and every sub-agent transcript beneath it.

    Args:
        session_jsonl: Path to the root session JSONL file.
        root_agent: Raw agent-setting value for the root thread. Sanitized
            internally; the caller keeps the raw value for display.

    Returns:
        A 2-tuple of ``(transcripts, subagent_types)``:

        - ``transcripts`` — depth-first pre-order, root first. Only files
          that exist are included.
        - ``subagent_types`` — sanitized ``agentType`` for every
          ``*.meta.json`` encountered, including ones whose JSONL is
          missing. Not de-duplicated; the caller decides.
    """
    session_id = session_jsonl.stem
    root_sanitized = sanitize_agent_name(root_agent)

    transcripts: list[AgentTranscript] = [
        AgentTranscript(
            jsonl_path=session_jsonl,
            agent_type=root_sanitized,
            agent_path=(root_sanitized,),
        )
    ]
    subagent_types: list[str] = []

    _walk_subagents(
        parent_session_dir=session_jsonl.parent / session_id,
        parent_path=(root_sanitized,),
        subagent_types_accumulator=subagent_types,
        visited=set(),
        depth=1,
        overflow_emitted=[False],
        cycle_emitted=[False],
        oserror_emitted=[False],
        out=transcripts,
    )
    return transcripts, subagent_types


def _resolve_for_cycle_check(
    directory: Path,
    visited: set[Path],
    cycle_emitted: list[bool],
    oserror_emitted: list[bool],
) -> Path | None:
    """Resolve ``directory`` and apply the shared cycle/OSError defense.

    Shared by both entry shapes ``_walk_subagents`` traverses (ordinary
    ``subagents/<agent_id>/`` directories and ``subagents/workflows/wf_*/``
    directories) so cycle detection and the one-warning-per-session flags
    are never reimplemented separately per shape.

    Args:
        directory: Directory to resolve and check against ``visited``.
        visited: Set of resolved ``Path`` objects already walked. Mutated
            in place with ``directory``'s resolved path on success.
        cycle_emitted: Single-element mutable flag for the cycle warning.
        oserror_emitted: Single-element mutable flag for the OSError warning.

    Returns:
        The resolved real path if ``directory`` should be traversed, or
        ``None`` if it should be skipped (already visited, or unreadable).
    """
    # On POSIX, symlinks are fully resolved; on Windows, junctions may not
    # be normalized (fallback to depth cap). OSError can occur on broken
    # symlinks, revoked permissions, or other filesystem faults — warn
    # once and skip rather than crash.
    try:
        real_dir = directory.resolve()
    except OSError as exc:
        if not oserror_emitted[0]:
            warnings.warn(
                f"Skipping unreadable subagent directory {directory}: {exc}",
                UserWarning,
                stacklevel=3,
            )
            oserror_emitted[0] = True
        return None
    if real_dir in visited:
        if not cycle_emitted[0]:
            warnings.warn(
                f"Subagent directory cycle detected: {real_dir}",
                UserWarning,
                stacklevel=3,
            )
            cycle_emitted[0] = True
        return None
    visited.add(real_dir)
    return real_dir


def _walk_meta_files(
    agent_dir: Path,
    parent_path: tuple[str, ...],
    subagent_types_accumulator: list[str],
    visited: set[Path],
    depth: int,
    overflow_emitted: list[bool],
    cycle_emitted: list[bool],
    oserror_emitted: list[bool],
    out: list[AgentTranscript],
) -> None:
    """Process every ``*.meta.json`` directly inside ``agent_dir``.

    Shared by both entry shapes: ordinary ``subagents/`` directories (one
    agent per subdirectory) and ``subagents/workflows/wf_*/`` directories
    (multiple agent-id pairs flat inside one directory). For each meta file
    found, an agent is recorded and recursed into at
    ``agent_dir / agent_id / "subagents"`` — the same shape either way.

    Args:
        agent_dir: Directory to glob ``*.meta.json`` files directly inside.
        parent_path: ``agent_path`` tuple of the *parent* agent.
        subagent_types_accumulator: Mutable list collecting all sanitized
            agent type names encountered at any depth.
        visited: Set of resolved ``Path`` objects already walked.
        depth: Current recursion depth (1 = first sub-agent level).
        overflow_emitted: Single-element mutable flag for the path-cap warning.
        cycle_emitted: Single-element mutable flag for the cycle warning.
        oserror_emitted: Single-element mutable flag for the OSError warning.
        out: Accumulator the discovered transcripts are appended to.
    """
    for meta_path in agent_dir.glob("*.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            raw_agent_type = meta.get("agentType") or "unknown"
        except (json.JSONDecodeError, OSError):
            raw_agent_type = "unknown"

        agent_type_sanitized = sanitize_agent_name(raw_agent_type)
        subagent_types_accumulator.append(agent_type_sanitized)

        child_path = parent_path + (agent_type_sanitized,)

        agent_id = meta_path.stem.replace(".meta", "")
        sub_jsonl = agent_dir / f"{agent_id}.jsonl"
        if sub_jsonl.is_file():
            out.append(
                AgentTranscript(
                    jsonl_path=sub_jsonl,
                    agent_type=agent_type_sanitized,
                    agent_path=child_path,
                )
            )

        _walk_subagents(
            parent_session_dir=agent_dir / agent_id,
            parent_path=child_path,
            subagent_types_accumulator=subagent_types_accumulator,
            visited=visited,
            depth=depth + 1,
            overflow_emitted=overflow_emitted,
            cycle_emitted=cycle_emitted,
            oserror_emitted=oserror_emitted,
            out=out,
        )


def _walk_subagents(
    parent_session_dir: Path,
    parent_path: tuple[str, ...],
    subagent_types_accumulator: list[str],
    visited: set[Path],
    depth: int,
    overflow_emitted: list[bool],
    cycle_emitted: list[bool],
    oserror_emitted: list[bool],
    out: list[AgentTranscript],
) -> None:
    """Walk ``<parent_session_dir>/subagents/`` and recurse into each child.

    Appends to ``out`` in depth-first pre-order. See :func:`walk_session`
    for the caller-visible contract.

    Contract (preserved verbatim from the pre-extraction parser, extended
    for issue #253's ``workflows/`` handling):
        - ``len(parent_path) >= MAX_AGENT_PATH_LENGTH``: stop descending.
          Emit one ``UserWarning`` per session (de-duped via
          ``overflow_emitted[0]``).
        - ``parent_session_dir/subagents`` already in ``visited``: emit a
          cycle ``UserWarning`` (de-duped via ``cycle_emitted[0]``) and stop.
        - ``OSError`` from ``resolve()``: emit a warning (de-duped via
          ``oserror_emitted[0]``) and stop.
        - For each ``*.meta.json`` directly inside ``subagents/``: read
          ``agentType`` (empty string and ``None`` both default to
          ``"unknown"``), sanitize it, append to the accumulator, build the
          child path, emit the child's JSONL if it exists, and recurse.
        - Missing JSONL: silently skipped, but the type is still recorded.
        - Empty or non-existent ``subagents/``: no-op.
        - ``subagents/workflows/wf_*/`` directories (one per ``Workflow()``
          dispatch): each is a *flat* sibling of ordinary
          ``subagents/<agent_id>/`` — multiple agent-id ``*.meta.json`` /
          ``*.jsonl`` pairs live directly inside one ``wf_<id>/`` directory,
          rather than one directory per agent. Each such meta file is
          processed exactly like an ordinary subagent entry (same
          accumulator, same ``child_path`` construction with no synthetic
          "workflow" or "wf_<id>" path segment, same missing-JSONL rule),
          and each agent found recurses into its own
          ``wf_<id>/<agent_id>/subagents/`` the same way an ordinary
          subagent recurses into ``subagents/<agent_id>/subagents/``. The
          depth cap, cycle defense, and warning flags are shared with the
          ordinary path via the same recursive call and the same mutable
          ``visited``/flag arguments — not reimplemented separately.

    Args:
        parent_session_dir: Directory for the parent agent session.
        parent_path: ``agent_path`` tuple of the *parent* agent.
        subagent_types_accumulator: Mutable list collecting all sanitized
            agent type names encountered at any depth.
        visited: Set of resolved ``Path`` objects already walked.
        depth: Current recursion depth (1 = first sub-agent level).
        overflow_emitted: Single-element mutable flag for the path-cap warning.
        cycle_emitted: Single-element mutable flag for the cycle warning.
        oserror_emitted: Single-element mutable flag for the OSError warning.
        out: Accumulator the discovered transcripts are appended to.
    """
    if len(parent_path) >= MAX_AGENT_PATH_LENGTH:
        if not overflow_emitted[0]:
            warnings.warn(
                f"Subagent path length cap ({MAX_AGENT_PATH_LENGTH})"
                f" exceeded at {parent_session_dir}",
                UserWarning,
                stacklevel=2,
            )
            overflow_emitted[0] = True
        return

    subagent_dir = parent_session_dir / "subagents"
    if not subagent_dir.is_dir():
        return

    if (
        _resolve_for_cycle_check(subagent_dir, visited, cycle_emitted, oserror_emitted)
        is None
    ):
        return

    _walk_meta_files(
        agent_dir=subagent_dir,
        parent_path=parent_path,
        subagent_types_accumulator=subagent_types_accumulator,
        visited=visited,
        depth=depth,
        overflow_emitted=overflow_emitted,
        cycle_emitted=cycle_emitted,
        oserror_emitted=oserror_emitted,
        out=out,
    )

    for wf_dir in subagent_dir.glob("workflows/wf_*"):
        if not wf_dir.is_dir():
            continue
        if (
            _resolve_for_cycle_check(wf_dir, visited, cycle_emitted, oserror_emitted)
            is None
        ):
            continue

        _walk_meta_files(
            agent_dir=wf_dir,
            parent_path=parent_path,
            subagent_types_accumulator=subagent_types_accumulator,
            visited=visited,
            depth=depth,
            overflow_emitted=overflow_emitted,
            cycle_emitted=cycle_emitted,
            oserror_emitted=oserror_emitted,
            out=out,
        )
