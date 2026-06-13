"""Parse Claude Code session JSONL files and subagent metadata."""

from __future__ import annotations

import json
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path

from claude_prospector.constants import (
    AGENT_PATH_SEPARATOR as _PATH_SEPARATOR,
    SANITIZED_SEPARATOR_REPLACEMENT as _SANITIZED_SEPARATOR_REPLACEMENT,
)
from claude_prospector.models import MessageRecord, SessionRecord

_MAX_AGENT_PATH_LENGTH = 10


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
    """Parse an ISO 8601 timestamp string to a datetime."""
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)


def _extract_skill(content: list[dict]) -> str | None:
    """Extract skill name from assistant message content blocks."""
    for block in content:
        if (
            block.get("type") == "tool_use"
            and block.get("name") == "Skill"
            and isinstance(block.get("input"), dict)
        ):
            return block["input"].get("skill")
    return None


def _parse_jsonl_messages(
    jsonl_path: Path,
    agent_type: str,
    agent_path: tuple[str, ...] = (),
) -> list[MessageRecord]:
    """Parse assistant messages from a JSONL file, attributing to agent."""
    messages: list[MessageRecord] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue

            msg = entry.get("message", {})
            usage = msg.get("usage")
            model = msg.get("model")
            if not usage or not model:
                continue

            content = msg.get("content", [])
            skill = _extract_skill(content) if isinstance(content, list) else None

            timestamp = _parse_timestamp(entry["timestamp"])

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
                )
            )
    return messages


def _sanitize_agent_name(name: str) -> str:
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


def _parse_subagents_recursive(
    parent_session_dir: Path,
    parent_path: tuple[str, ...],
    subagent_types_accumulator: list[str],
    visited: set[Path],
    depth: int,
    overflow_emitted: list[bool],
    cycle_emitted: list[bool],
    oserror_emitted: list[bool],
) -> list[MessageRecord]:
    """Walk <parent_session_dir>/subagents/ and recurse into each sub-agent.

    Implements a depth-first walk of the subagent tree rooted at
    ``parent_session_dir``. Each level reads ``*.meta.json`` files, parses
    the matching JSONL, and recurses into the sub-agent's own session
    directory.

    Contract:
        - ``len(parent_path) >= _MAX_AGENT_PATH_LENGTH``: return ``[]``.
          Emit one ``UserWarning`` per session (de-duped via
          ``overflow_emitted[0]``).
        - ``parent_session_dir.resolve()`` already in ``visited``: emit a
          cycle ``UserWarning`` (de-duped via ``cycle_emitted[0]``) and
          return ``[]``.
        - ``OSError`` from ``resolve()``: emit a warning (de-duped via
          ``oserror_emitted[0]``) and return ``[]``.
        - For each ``*.meta.json``: read ``agentType`` (empty string and
          ``None`` both default to ``"unknown"``), sanitize it, append to
          accumulator, build child path, parse matching JSONL, and recurse
          into ``<parent_session_dir>/subagents/<agent_id>/``.
        - Missing JSONL: silently skipped.
        - Empty or non-existent ``subagents/``: returns ``[]``.

    Args:
        parent_session_dir: Directory for the parent agent session
            (contains a ``subagents/`` subdirectory if any children exist).
        parent_path: ``agent_path`` tuple of the *parent* agent — child
            paths are derived by appending the child agent's sanitized name.
        subagent_types_accumulator: Mutable list collecting all sanitized
            agent type names encountered at any depth.
        visited: Set of resolved ``Path`` objects already walked; prevents
            infinite recursion through symlink or junction cycles.
        depth: Current recursion depth (1 = first sub-agent level under
            the root session).
        overflow_emitted: Single-element list used as a mutable flag; set
            to ``True`` once the path-length-cap warning has been emitted so
            it fires at most once per ``_parse_session`` call.
        cycle_emitted: Single-element list used as a mutable flag; set to
            ``True`` once the cycle warning has been emitted so it fires at
            most once per ``_parse_session`` call.
        oserror_emitted: Single-element list used as a mutable flag; set to
            ``True`` once the OSError warning has been emitted so it fires
            at most once per ``_parse_session`` call.

    Returns:
        Flat list of ``MessageRecord`` objects produced at this level and
        all reachable descendant levels.
    """
    if len(parent_path) >= _MAX_AGENT_PATH_LENGTH:
        if not overflow_emitted[0]:
            warnings.warn(
                f"Subagent path length cap ({_MAX_AGENT_PATH_LENGTH})"
                f" exceeded at {parent_session_dir}",
                UserWarning,
                stacklevel=2,
            )
            overflow_emitted[0] = True
        return []

    subagent_dir = parent_session_dir / "subagents"
    if not subagent_dir.is_dir():
        return []

    # Cycle defense: resolve the subagents directory to its canonical real
    # path.  On POSIX, symlinks are fully resolved; on Windows, junctions
    # may not be normalized (fallback to depth cap).
    # OSError can occur on broken symlinks, revoked permissions, or
    # other filesystem faults — warn once and skip rather than crash.
    try:
        real_dir = subagent_dir.resolve()
    except OSError as exc:
        if not oserror_emitted[0]:
            warnings.warn(
                f"Skipping unreadable subagent directory {subagent_dir}: {exc}",
                UserWarning,
                stacklevel=2,
            )
            oserror_emitted[0] = True
        return []
    if real_dir in visited:
        if not cycle_emitted[0]:
            warnings.warn(
                f"Subagent directory cycle detected: {real_dir}",
                UserWarning,
                stacklevel=2,
            )
            cycle_emitted[0] = True
        return []
    visited.add(real_dir)

    messages: list[MessageRecord] = []
    for meta_path in subagent_dir.glob("*.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            raw_agent_type = meta.get("agentType") or "unknown"
        except (json.JSONDecodeError, OSError):
            raw_agent_type = "unknown"

        agent_type_sanitized = _sanitize_agent_name(raw_agent_type)
        subagent_types_accumulator.append(agent_type_sanitized)

        child_path = parent_path + (agent_type_sanitized,)

        # Find matching JSONL in the parent's subagents/ directory
        agent_id = meta_path.stem.replace(".meta", "")
        sub_jsonl = subagent_dir / f"{agent_id}.jsonl"
        if sub_jsonl.is_file():
            messages.extend(
                _parse_jsonl_messages(
                    sub_jsonl,
                    agent_type=agent_type_sanitized,
                    agent_path=child_path,
                )
            )

        # Recurse into this sub-agent's own session directory
        child_session_dir = subagent_dir / agent_id
        messages.extend(
            _parse_subagents_recursive(
                parent_session_dir=child_session_dir,
                parent_path=child_path,
                subagent_types_accumulator=subagent_types_accumulator,
                visited=visited,
                depth=depth + 1,
                overflow_emitted=overflow_emitted,
                cycle_emitted=cycle_emitted,
                oserror_emitted=oserror_emitted,
            )
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

    # Sanitize root agent name before building the root path tuple.
    root_agent_sanitized = _sanitize_agent_name(root_agent)

    # Parse parent session messages
    messages = _parse_jsonl_messages(
        jsonl_path,
        agent_type=root_agent_sanitized,
        agent_path=(root_agent_sanitized,),
    )

    # Parse subagent messages via the recursive helper.
    subagent_types: list[str] = []
    visited: set[Path] = set()
    overflow_emitted: list[bool] = [False]
    cycle_emitted: list[bool] = [False]
    oserror_emitted: list[bool] = [False]
    messages.extend(
        _parse_subagents_recursive(
            parent_session_dir=jsonl_path.parent / session_id,
            parent_path=(root_agent_sanitized,),
            subagent_types_accumulator=subagent_types,
            visited=visited,
            depth=1,
            overflow_emitted=overflow_emitted,
            cycle_emitted=cycle_emitted,
            oserror_emitted=oserror_emitted,
        )
    )

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
