"""Parse Claude Code session JSONL files and subagent metadata."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from claude_prospector.models import (
    CommandInvocationRecord,
    MessageRecord,
    SessionMetadataObservation,
    SessionRecord,
    SkillInvocationRecord,
)
from claude_prospector.transcript_walker import walk_session


_COMMAND_ENVELOPE_RE = re.compile(
    r"\A\s*(?:"
    r"<command-message>[^<>]*</command-message>\s*"
    r"<command-name>(/[^\s<>]+)</command-name>"
    r"|"
    r"<command-name>(/[^\s<>]+)</command-name>"
    r"(?:\s*<command-message>[^<>]*</command-message>)?"
    r")\s*\Z"
)


def decode_project_hash(hash_name: str) -> str:
    """Decode a project hash directory name to a human-readable project name.

    Claude Code encodes project paths: '--' represents a path separator,
    '-' represents a hyphen or space within segment names. We split on '--'
    and take the last segment as the project name.

    Examples:
        'C--Users-chris--claude' -> 'claude'
        'i--games-raid-rsl-rule-generator' -> 'games-raid-rsl-rule-generator'
    """
    if not hash_name:
        return ""
    segments = hash_name.split("--")
    return segments[-1]


def decode_project_hash_full(hash_name: str) -> str:
    """Decode a project hash directory name to a full human-readable path.

    Unlike :func:`decode_project_hash`, which returns only the last path
    segment, this function reconstructs a readable approximation of the
    full original path by joining all ``--``-separated segments with
    ``/``.  A single-letter first segment is assumed to be a Windows drive
    letter and gets a ``:`` appended (e.g. ``C`` → ``C:``).

    The reconstruction is lossy — leading dots (e.g. ``.claude``) and the
    exact original separator character (``/`` vs ``\\``) are not
    preserved — but it is always more informative than the leaf-only result
    for deep paths.

    Examples:
        'C--Users-chris--claude' -> 'C:/Users/chris/claude'
        'i--games-skyrim-mods-oar-config-manager'
            -> 'i:/games/skyrim/mods/oar-config-manager'
        'C--Users-chris-AppData-Local-Programs-Open-Design-release-stable'
            -> 'C:/Users/chris-AppData-Local-Programs-Open-Design-release-stable'

    Args:
        hash_name: The slug directory name as encoded by Claude Code.

    Returns:
        A forward-slash-separated path string approximating the original
        path, or the original string when it contains no ``--`` separator.
    """
    if not hash_name:
        return ""
    segments = hash_name.split("--")
    if len(segments) == 1:
        # No '--' separator — return the segment unchanged.
        return hash_name
    # Normalise the first segment: single letter → Windows drive with colon.
    first = segments[0]
    if len(first) == 1 and first.isalpha():
        first = first + ":"
    rest = segments[1:]
    return "/".join([first] + rest)


def _fold_worktree_cwd_parts(parts: list[str]) -> str | None:
    """Return the owner-repo name from cwd parts when inside a worktree.

    Recognises two worktree layouts:

    * ``<repo>/.worktrees/<branch>`` — ``.worktrees`` at index *i* means
      the owner repo leaf is ``parts[i - 1]``.
    * ``<repo>/.claude/worktrees/<name>`` — ``worktrees`` at index *i*
      with ``parts[i - 1] == ".claude"`` means the owner repo leaf is
      ``parts[i - 2]``.

    Returns the owner-repo leaf string, or ``None`` when the parts list
    does not match either worktree pattern.

    Args:
        parts: Path components produced by splitting a cwd string on
            ``/`` and ``\\`` (trailing separators already stripped).

    Returns:
        Owner repo leaf name, or ``None`` if no worktree pattern matched.
    """
    for i, part in enumerate(parts):
        if part == ".worktrees" and i >= 1:
            return parts[i - 1]
        if part == "worktrees" and i >= 2 and parts[i - 1] == ".claude":
            return parts[i - 2]
    return None


def _fold_worktree_slug_segments(segments: list[str]) -> str | None:
    """Return the owner-repo name from slug ``--``-segments for worktrees.

    In the Claude Code slug encoding each path component separator becomes
    ``--``, while hyphens within a component name stay as ``-``.  The
    ``.`` in ``.worktrees`` is dropped, producing a segment that starts
    with ``"worktrees-"``.  For ``.claude/worktrees`` the two components
    merge into a segment starting with ``"claude-worktrees-"``.

    When a matching segment is found at index *i*, the owner repo is the
    segment at ``i - 1``.  Because the segment may encode several path
    components joined by ``-`` (due to the lossiness of the slug encoding),
    we extract the project name as the **last two ``-``-separated tokens**
    of the owner segment — a heuristic that recovers a two-word repo name
    such as ``"my-api"`` from a composite segment such as
    ``"repos-my-api"``.

    Args:
        segments: The ``--``-split components of a Claude Code project
            slug, e.g. ``["I", "ai-claude-claude-prospector",
            "worktrees-fix-auth"]``.

    Returns:
        Owner repo name string, or ``None`` if no worktree segment found.

    Note:
        **Known limitation (accepted, issue #232):** this path is
        best-effort.  The slug encoding flattens ``/`` boundaries into
        ``-``, so a multi-token repo name (e.g. ``my-awesome-api``) may
        be truncated to its last two tokens (``awesome-api``).  This can
        split such a repo across dashboard rows for sessions that have no
        ``cwd``.  The cwd-based path in ``derive_project_name`` is
        unaffected and correct.  Do not change this heuristic without
        revisiting issue #232.
    """
    for i, seg in enumerate(segments):
        if (
            seg.startswith("worktrees-") or seg.startswith("claude-worktrees-")
        ) and i >= 1:
            owner_seg = segments[i - 1]
            # The owner segment may encode a chain of path components
            # as hyphen-separated tokens (lossy).  Take the last two
            # tokens to recover a two-word project name; single-token
            # names fall out naturally.
            tokens = owner_seg.split("-")
            return "-".join(tokens[-2:]) if len(tokens) >= 2 else owner_seg
    return None


def derive_project_name(
    cwd: str | None,
    slug_fallback: str | None,
) -> str:
    """Derive a human-readable project name from a cwd path or a slug.

    Strategy (applied in order):

    1. When *cwd* is a non-empty string, split on both ``/`` and ``\\``
       (so Windows paths analysed on Linux still resolve correctly) and
       check for a git worktree layout:

       * ``<repo>/.worktrees/<branch>`` → resolve to ``<repo>`` leaf.
       * ``<repo>/.claude/worktrees/<name>`` → resolve to ``<repo>`` leaf.
       * Otherwise fall back to the plain leaf directory (existing
         behaviour — no regression for non-worktree paths).

    2. When *slug_fallback* is a non-empty string, apply the equivalent
       worktree-folding logic on the ``--``-separated segments, then fall
       back to ``decode_project_hash`` for non-worktree slugs.
    3. Final fallback: ``"unknown"``.

    This logic is intentionally shared between the dashboard pipeline
    (``parse_sessions``) and the ``session_summary`` subcommand
    (``_derive_project``) so both surfaces benefit from the cwd-first
    strategy without duplication.

    Args:
        cwd: The ``cwd`` field value from a JSONL entry, or ``None``
            when no cwd entry exists in the session.
        slug_fallback: The encoded project directory name (e.g.
            ``"C--Users-chris--claude"``), used as a fallback when no
            cwd is available.

    Returns:
        A non-empty project name string.
    """
    if cwd and isinstance(cwd, str):
        # Split on both forward- and back-slashes, ignoring trailing
        # separators, so Windows paths analysed on Linux (where pathlib
        # treats '\' as a literal character) still yield the correct leaf.
        parts = re.split(r"[\\/]+", cwd.rstrip("\\/"))
        # Attempt worktree folding before falling back to the leaf.
        name = _fold_worktree_cwd_parts(parts) or (parts[-1] if parts else "")
        if name:
            return name

    if slug_fallback:
        segments = slug_fallback.split("--")
        folded = _fold_worktree_slug_segments(segments)
        if folded:
            return folded
        decoded = decode_project_hash(slug_fallback)
        if decoded:
            return decoded

    return "unknown"


def _load_exclude_patterns(config_path: Path) -> list[str]:
    """Load project exclude patterns from config.json.

    Reads ``config_path`` and returns the value of the
    ``project_exclude_patterns`` key as a list of strings.  Returns an
    empty list when the file is absent, the key is missing, or the
    file is not valid JSON.

    The patterns are simple substring matches applied to the full
    ``project_path`` string.  A session whose ``project_path`` contains
    any listed pattern is excluded from the parsed output.

    Args:
        config_path: Path to the ``config.json`` file.

    Returns:
        List of substring patterns (may be empty).
    """
    if not config_path.exists():
        return []
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        patterns = cfg.get("project_exclude_patterns", [])
        if isinstance(patterns, list):
            return [str(p) for p in patterns if p]
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _is_excluded(project_path: str, patterns: list[str]) -> bool:
    """Return True when project_path matches any exclude pattern.

    Matching is a case-sensitive substring check.  No glob expansion
    is performed — each pattern is tested with the ``in`` operator
    against *project_path*.

    Args:
        project_path: The full project path string to test.
        patterns: List of substring patterns from the config.

    Returns:
        ``True`` when any pattern matches; ``False`` otherwise.
    """
    for pattern in patterns:
        if pattern in project_path:
            return True
    return False


_CWD_SCAN_LINES = 20


def _read_cwd_from_jsonl(jsonl_path: Path) -> str | None:
    """Read the first non-empty ``cwd`` field from a JSONL session file.

    Scans the first ``_CWD_SCAN_LINES`` lines for any entry with a
    non-empty ``cwd`` string field.  Returns ``None`` when no such entry
    is found within the scan window.

    Args:
        jsonl_path: Path to the session ``.jsonl`` file.

    Returns:
        The cwd string from the first matching entry, or ``None``.
    """
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for _ in range(_CWD_SCAN_LINES):
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = entry.get("cwd")
                if cwd and isinstance(cwd, str):
                    return cwd
    except OSError:
        pass
    return None


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse an offset-aware ISO 8601 timestamp string.

    Raises:
        ValueError: If the timestamp is invalid or omits a UTC offset.
    """
    ts_str = ts_str.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(ts_str)
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed


_SESSION_METADATA_FIELDS = {
    "gitBranch": "git_branch",
    "entrypoint": "entrypoint",
    "version": "claude_code_version",
}


def _parse_effort(value: object) -> str | None:
    """Normalize a transcript effort label without restricting future values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _extract_skill_invocations(
    content: list[dict],
    *,
    timestamp: datetime,
    agent_path: tuple[str, ...],
    message_id: str | None,
    entry_id: str | None,
    entry_ordinal: int,
    transcript_key: str,
) -> list[tuple[tuple[object, ...], SkillInvocationRecord]]:
    """Return every valid privacy-safe Skill block and its stable identity.

    Tool-use IDs deduplicate repeated transcript fragments. Entries without an
    ID use the transcript-local ordinal to keep distinct anonymous blocks from
    colliding while retaining no arguments or message content.
    """
    found: list[tuple[tuple[object, ...], SkillInvocationRecord]] = []
    for index, block in enumerate(content):
        if block.get("type") != "tool_use" or block.get("name") != "Skill":
            continue
        payload = block.get("input")
        skill = payload.get("skill") if isinstance(payload, dict) else None
        if not isinstance(skill, str) or not skill.strip():
            continue
        tool_use_id = block.get("id") if isinstance(block.get("id"), str) else ""
        identity = (
            ("tool", transcript_key, tool_use_id)
            if tool_use_id
            else (
                "fallback",
                transcript_key,
                message_id or entry_id or entry_ordinal,
                index,
                skill.strip(),
            )
        )
        found.append(
            (
                identity,
                SkillInvocationRecord(
                    skill=skill.strip(),
                    timestamp=timestamp,
                    agent_path=agent_path,
                    tool_use_id=tool_use_id,
                ),
            )
        )
    return found


def _extract_manual_command(entry: dict) -> CommandInvocationRecord | None:
    """Extract one privacy-safe manual command from an external user entry.

    Args:
        entry: Decoded transcript entry.

    Returns:
        A name-and-timestamp record when the canonical wrapper is valid;
        otherwise ``None``. Content inside ``<command-args>`` is never scanned.
    """
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    timestamp_raw = entry.get("timestamp")
    if not isinstance(content, str) or not isinstance(timestamp_raw, str):
        return None

    command_wrapper = content.partition("<command-args")[0]
    match = _COMMAND_ENVELOPE_RE.fullmatch(command_wrapper)
    if match is None:
        return None
    try:
        timestamp = _parse_timestamp(timestamp_raw)
    except ValueError:
        return None
    command_name = match.group(1) or match.group(2)
    return CommandInvocationRecord(name=command_name, timestamp=timestamp)


def _parse_jsonl_records(
    jsonl_path: Path,
    agent_type: str,
    agent_path: tuple[str, ...] = (),
    *,
    collect_commands: bool = True,
) -> tuple[
    list[MessageRecord],
    list[CommandInvocationRecord],
    list[SkillInvocationRecord],
    list[SessionMetadataObservation],
    int,
]:
    """Parse privacy-safe transcript facts in one pass.

    Args:
        jsonl_path: Transcript JSONL file to parse.
        agent_type: Leaf agent name assigned to assistant messages.
        agent_path: Full agent ancestry assigned to assistant messages.
        collect_commands: Whether to extract manual command records. This is
            enabled only for a session's root transcript.

    Returns:
        Assistant messages, manual commands, Skill invocations, allowlisted
        metadata observations, and duplicate-message effort conflict count.
        Stored records never retain prompts, thinking, Skill arguments, tool
        inputs, or tool-result content.
    """
    messages: list[MessageRecord] = []
    commands: list[CommandInvocationRecord] = []
    skill_invocations: list[SkillInvocationRecord] = []
    metadata_observations: list[SessionMetadataObservation] = []
    message_indexes: dict[str, int] = {}
    command_entry_ids: set[str] = set()
    skill_identities: set[tuple[object, ...]] = set()
    effort_conflicts = 0
    transcript_key = str(jsonl_path.resolve())
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for entry_ordinal, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            timestamp_raw = entry.get("timestamp")
            timestamp: datetime | None = None
            if isinstance(timestamp_raw, str):
                try:
                    timestamp = _parse_timestamp(timestamp_raw)
                except ValueError:
                    pass

            if timestamp is not None:
                for field_name, normalized_name in _SESSION_METADATA_FIELDS.items():
                    value = entry.get(field_name)
                    if isinstance(value, str) and value:
                        metadata_observations.append(
                            SessionMetadataObservation(
                                name=normalized_name,
                                value=value,
                                timestamp=timestamp,
                                agent_path=agent_path,
                            )
                        )

            if (
                collect_commands
                and entry.get("type") == "user"
                and entry.get("userType") == "external"
            ):
                entry_id = entry.get("uuid")
                if isinstance(entry_id, str) and entry_id in command_entry_ids:
                    continue
                command = _extract_manual_command(entry)
                if command is not None:
                    commands.append(command)
                    if isinstance(entry_id, str):
                        command_entry_ids.add(entry_id)

            if entry.get("type") != "assistant":
                continue

            msg = entry.get("message", {})
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            model = msg.get("model")
            if not usage or not model:
                continue

            content = msg.get("content", [])
            if timestamp is None:
                continue

            message_id = msg.get("id")
            message_id = message_id if isinstance(message_id, str) else None
            entry_id = entry.get("uuid")
            entry_id = entry_id if isinstance(entry_id, str) else None
            skill_records = (
                _extract_skill_invocations(
                    content,
                    timestamp=timestamp,
                    agent_path=agent_path,
                    message_id=message_id,
                    entry_id=entry_id,
                    entry_ordinal=entry_ordinal,
                    transcript_key=transcript_key,
                )
                if isinstance(content, list)
                else []
            )
            for identity, record in skill_records:
                if identity not in skill_identities:
                    skill_identities.add(identity)
                    skill_invocations.append(record)
            skill = skill_records[0][1].skill if skill_records else None

            candidate_effort = _parse_effort(entry.get("effort"))

            if message_id is not None and message_id in message_indexes:
                message_index = message_indexes[message_id]
                existing = messages[message_index]
                if existing.skill is None and skill is not None:
                    messages[message_index] = replace(existing, skill=skill)
                    existing = messages[message_index]
                if existing.effort is None and candidate_effort is not None:
                    messages[message_index] = replace(existing, effort=candidate_effort)
                elif (
                    existing.effort is not None
                    and candidate_effort is not None
                    and existing.effort != candidate_effort
                ):
                    effort_conflicts += 1
                # Fragment lines repeat the message's final usage snapshot;
                # summing duplicate IDs would multiply every usage field.
                continue

            messages.append(
                MessageRecord(
                    timestamp=timestamp,
                    model=model,
                    agent_type=agent_type,
                    skill=skill,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    agent_path=agent_path,
                    effort=candidate_effort,
                )
            )
            if message_id is not None:
                message_indexes[message_id] = len(messages) - 1
    return (
        messages,
        commands,
        skill_invocations,
        metadata_observations,
        effort_conflicts,
    )


def _parse_jsonl_messages(
    jsonl_path: Path,
    agent_type: str,
    agent_path: tuple[str, ...] = (),
) -> list[MessageRecord]:
    """Parse assistant messages from a JSONL file, attributing to agent.

    Args:
        jsonl_path: Transcript JSONL file to parse.
        agent_type: Leaf agent name assigned to assistant messages.
        agent_path: Full agent ancestry assigned to assistant messages.

    Returns:
        Parsed assistant message records.
    """
    messages, _, _, _, _ = _parse_jsonl_records(
        jsonl_path,
        agent_type,
        agent_path,
        collect_commands=False,
    )
    return messages


_AGENT_SETTING_SCAN_LINES = 10


def _parse_session(
    jsonl_path: Path,
    project_name: str,
    project_path: str = "",
) -> SessionRecord | None:
    """Parse a single session JSONL file and its subagents.

    Agent-setting resolution uses a three-branch strategy to handle recent
    Claude Code versions that prepend a ``last-prompt`` line before the
    ``agent-setting`` line:

    1. **Bounded scan**: read the first ``_AGENT_SETTING_SCAN_LINES`` lines;
       use the ``agentSetting`` value from the first ``agent-setting`` entry.
    2. **Subagents fallback**: if no ``agent-setting`` was found and the
       ``<session_id>/subagents/`` directory exists (only the router spawns
       sub-agents, implying general-purpose), set ``root_agent`` to
       ``"general-purpose"``.
    3. **Main fallback**: plain top-level CLI sessions that have no
       ``agent-setting`` record and no subagents directory default to
       ``"main"`` rather than ``"unknown"``.
    4. **Unknown preserved**: degenerate cases (empty file, all-malformed JSON,
       file unreadable) retain ``"unknown"`` so they are not silently mislabelled.
    """
    session_id = jsonl_path.stem

    # Resolve the subagent directory early — needed for the fallback branch.
    subagent_dir = jsonl_path.parent / session_id / "subagents"

    # Branch 1: bounded scan for agent-setting in the first N lines.
    # Track whether any parseable line was seen to distinguish a populated
    # session (no agent-setting → "main") from an empty/degenerate one
    # (no lines at all → "unknown").
    root_agent = "unknown"
    saw_any_line = False
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for _ in range(_AGENT_SETTING_SCAN_LINES):
            raw = f.readline()
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            saw_any_line = True
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "agent-setting":
                root_agent = entry.get("agentSetting", "unknown")
                break

    # Branch 2: subagents-directory fallback when no agent-setting found.
    if root_agent == "unknown" and subagent_dir.is_dir():
        root_agent = "general-purpose"

    # Branch 3: populated session with no agent-setting and no subagents/ dir
    # → top-level main-thread CLI session.
    if root_agent == "unknown" and saw_any_line:
        root_agent = "main"

    # Locate every agent transcript in this session, then parse each one.
    transcripts, subagent_types = walk_session(jsonl_path, root_agent)

    messages: list[MessageRecord] = []
    commands: list[CommandInvocationRecord] = []
    skill_invocations: list[SkillInvocationRecord] = []
    metadata_observations: list[SessionMetadataObservation] = []
    effort_conflicts = 0
    for unit in transcripts:
        (
            unit_messages,
            unit_commands,
            unit_skill_invocations,
            unit_metadata_observations,
            unit_effort_conflicts,
        ) = _parse_jsonl_records(
            unit.jsonl_path,
            agent_type=unit.agent_type,
            agent_path=unit.agent_path,
            collect_commands=unit.jsonl_path == jsonl_path,
        )
        messages.extend(unit_messages)
        commands.extend(unit_commands)
        skill_invocations.extend(unit_skill_invocations)
        metadata_observations.extend(unit_metadata_observations)
        effort_conflicts += unit_effort_conflicts

    if not messages:
        start_time = datetime.now(timezone.utc)
    else:
        start_time = min(m.timestamp for m in messages)

    return SessionRecord(
        session_id=session_id,
        project=project_name,
        project_path=project_path,
        start_time=start_time,
        root_agent=root_agent,
        messages=messages,
        subagent_types=sorted(set(subagent_types)),
        commands=commands,
        skill_invocations=skill_invocations,
        metadata_observations=metadata_observations,
        agent_paths=[unit.agent_path for unit in transcripts],
        effort_conflicts=effort_conflicts,
    )


def parse_sessions(data_dir: Path) -> list[SessionRecord]:
    """Parse all sessions from a Claude Code data directory.

    Each session's ``project`` field is derived cwd-first: if any JSONL
    entry in the session carries a ``cwd`` field, the leaf directory of
    that path is used.  Otherwise the project directory slug is decoded
    via :func:`decode_project_hash`.  The ``project_path`` field carries
    the full original ``cwd`` when available, or the full decoded slug
    from :func:`decode_project_hash_full` as a fallback.

    Sessions whose ``project_path`` matches any entry in the
    ``project_exclude_patterns`` list in ``config.json`` are silently
    omitted from the result.  The config file is resolved via
    :func:`claude_prospector.paths.config_path`.

    Args:
        data_dir: Path to the Claude data directory (e.g. ~/.claude).
                  Sessions are in data_dir/projects/<hash>/<session>.jsonl

    Returns:
        List of SessionRecord objects, sorted by start_time descending.
    """
    from claude_prospector.paths import config_path as _config_path

    projects_dir = data_dir / "projects"
    if not projects_dir.is_dir():
        return []

    exclude_patterns = _load_exclude_patterns(_config_path())

    sessions: list[SessionRecord] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        slug = project_dir.name

        for jsonl_path in project_dir.glob("*.jsonl"):
            # Derive cwd from the session JSONL, then compute names.
            cwd = _read_cwd_from_jsonl(jsonl_path)
            project_name = derive_project_name(cwd, slug)
            project_path = cwd if cwd else decode_project_hash_full(slug)

            # Config-driven exclude: skip sessions from noise directories.
            if exclude_patterns and _is_excluded(project_path, exclude_patterns):
                continue

            session = _parse_session(jsonl_path, project_name, project_path)
            if session is not None:
                sessions.append(session)

    sessions.sort(key=lambda s: s.start_time, reverse=True)
    return sessions
