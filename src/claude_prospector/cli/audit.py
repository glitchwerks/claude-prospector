"""Audit subcommand for claude-prospector.

Deterministically inventories agents and skills from all effective
Claude Code sources (user-scope, project-scope, plugin cache, and
Windows Claude Desktop), detects name collisions, computes Jaccard
semantic overlaps, identifies tool-coupling mismatches, and flags
cache-hygiene issues.

Exit codes:
    0  Success — report written to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public API (used by tests and __main__)
# ---------------------------------------------------------------------------


def build_parser(
    parent: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    """Register the 'audit' subparser and return it.

    Args:
        parent: The subparsers action from the top-level parser.

    Returns:
        The configured audit ArgumentParser.
    """
    p = parent.add_parser(
        "audit",
        help=(
            "Inventory agents/skills, detect collisions, overlaps, "
            "tool-coupling mismatches, and cache-hygiene issues."
        ),
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["markdown", "json"],
        default="markdown",
        help=(
            "Output format: 'markdown' (default) or 'json' for "
            "machine-readable output."
        ),
    )
    p.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Override cwd for project-scope walk (default: cwd).",
    )
    p.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Override home directory for testability (default: ~).",
    )
    return p


def run(args: argparse.Namespace) -> int:
    """Execute the audit subcommand.

    Args:
        args: Parsed argument namespace from the audit subparser.

    Returns:
        Integer exit code (always 0 on success).
    """
    home_dir = args.home if args.home is not None else Path.home()
    project_dir = (
        args.project_dir if args.project_dir is not None else Path(os.getcwd())
    )

    output = run_audit(
        home_dir=home_dir,
        project_dir=project_dir,
        output_format=args.output_format,
    )
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def run_audit(
    home_dir: Path,
    project_dir: Path,
    output_format: str = "markdown",
    threshold: float = 0.5,
) -> str:
    """Run the full audit and return the report as a string.

    This is the primary entry point for programmatic use and for tests
    that need to inspect the raw output.

    Args:
        home_dir: Path to the user home directory (~).
        project_dir: Path to the project root for project-scope walks.
        output_format: ``"markdown"`` or ``"json"``.
        threshold: Jaccard similarity threshold for semantic overlaps
            (default 0.5).

    Returns:
        The audit report as a string (markdown or JSON).
    """
    items = collect_items(home_dir=home_dir, project_dir=project_dir)
    collisions = find_collisions(items)
    overlaps = find_semantic_overlaps(items, threshold=threshold)
    tool_coupling = find_tool_coupling_issues(items)
    cache_hygiene = check_cache_hygiene(home_dir=home_dir)

    if output_format == "json":
        return _render_json(
            items=items,
            collisions=collisions,
            overlaps=overlaps,
            tool_coupling=tool_coupling,
            cache_hygiene=cache_hygiene,
        )
    return _render_markdown(
        items=items,
        collisions=collisions,
        overlaps=overlaps,
        tool_coupling=tool_coupling,
        cache_hygiene=cache_hygiene,
    )


# ---------------------------------------------------------------------------
# Source collection
# ---------------------------------------------------------------------------


def collect_items(
    home_dir: Path,
    project_dir: Path,
) -> list[dict[str, Any]]:
    """Walk all effective Claude Code sources and return parsed items.

    Source walk order:

    1. ``<home>/.claude/agents/*.md``          → _kind=custom-user, _type=agent
    2. ``<home>/.claude/skills/*/SKILL.md``    → _kind=custom-user, _type=skill
    3. ``<project>/.claude/agents/*.md``       → _kind=custom-project, _type=agent
    4. ``<project>/.claude/skills/*/SKILL.md`` → _kind=custom-project, _type=skill
    5. Plugin cache (latest version per plugin) → _kind=plugin:<name>
    6. Windows Claude Desktop skills           → _kind=claude-desktop

    Args:
        home_dir: Path to the user home directory.
        project_dir: Path to the project root.

    Returns:
        A list of frontmatter dicts, each augmented with ``_kind``,
        ``_type``, and ``_path`` keys.
    """
    items: list[dict[str, Any]] = []

    # 1 & 2: user-scope
    _walk_agents(
        home_dir / ".claude" / "agents",
        kind="custom-user",
        items=items,
    )
    _walk_skills(
        home_dir / ".claude" / "skills",
        kind="custom-user",
        items=items,
    )

    # 3 & 4: project-scope
    _walk_agents(
        project_dir / ".claude" / "agents",
        kind="custom-project",
        items=items,
    )
    _walk_skills(
        project_dir / ".claude" / "skills",
        kind="custom-project",
        items=items,
    )

    # 5: plugin cache (deduplicated to latest version)
    _walk_plugin_cache(home_dir, items)

    # 6: Windows Claude Desktop
    _walk_claude_desktop(home_dir, items)

    return items


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------


def find_collisions(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect direct name collisions among collected items.

    A collision occurs when two or more items share the same ``_type``
    and ``name``.

    Args:
        items: Items returned by :func:`collect_items`.

    Returns:
        A list of collision records, each with keys:
        ``type``, ``name``, ``sources`` (list of _kind strings).
    """
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        key = (item["_type"], item.get("name", ""))
        by_key[key].append(item)

    collisions = []
    for (item_type, name), group in sorted(by_key.items()):
        if len(group) > 1:
            collisions.append(
                {
                    "type": item_type,
                    "name": name,
                    "sources": [g["_kind"] for g in group],
                    "paths": [g["_path"] for g in group],
                }
            )
    return collisions


def find_semantic_overlaps(
    items: list[dict[str, Any]],
    threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Find pairs of items whose description bigrams overlap significantly.

    Uses bigram Jaccard similarity: tokenise descriptions into adjacent
    word pairs, compute |A ∩ B| / |A ∪ B|.  Only same-type pairs with
    *different* names are compared.

    Args:
        items: Items returned by :func:`collect_items`.
        threshold: Minimum Jaccard score to report (default 0.5).

    Returns:
        A list of overlap records, each with keys:
        ``type``, ``names`` (2-element list), ``kinds`` (2-element list),
        ``score`` (float).
    """
    overlaps: list[dict[str, Any]] = []

    for item_type in ("agent", "skill"):
        typed = [i for i in items if i["_type"] == item_type]
        seen: set[tuple[str, ...]] = set()

        for idx, item_a in enumerate(typed):
            for item_b in typed[idx + 1 :]:
                name_a = item_a.get("name", "")
                name_b = item_b.get("name", "")

                if not name_a or not name_b or name_a == name_b:
                    continue

                # Deduplicate the pair regardless of order
                pair_key = tuple(
                    sorted(
                        [
                            name_a,
                            name_b,
                            item_a["_kind"],
                            item_b["_kind"],
                        ]
                    )
                )
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                score = _jaccard_bigram(
                    item_a.get("description", ""),
                    item_b.get("description", ""),
                )
                if score >= threshold:
                    overlaps.append(
                        {
                            "type": item_type,
                            "names": [name_a, name_b],
                            "kinds": [item_a["_kind"], item_b["_kind"]],
                            "score": round(score, 4),
                        }
                    )

    return overlaps


def find_tool_coupling_issues(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect tool-coupling mismatches between agents and skills.

    For each skill, scan the body text for ``mcp__*`` tool mentions and
    for the literal words ``PowerShell``/``Bash``.  For each agent, parse
    its ``tools`` frontmatter field.  When a skill mentions a tool or
    shell that an agent does not list, emit a warning.

    This is heuristic — skills may guard availability. Surfaces as
    warnings, not errors.

    Args:
        items: Items returned by :func:`collect_items`.

    Returns:
        A list of warning records, each with keys:
        ``agent``, ``agent_kind``, ``skill``, ``skill_kind``,
        ``missing_tool``.
    """
    agents = [i for i in items if i["_type"] == "agent"]
    skills = [i for i in items if i["_type"] == "skill"]

    warnings: list[dict[str, Any]] = []

    for skill in skills:
        skill_tools = _extract_skill_tool_refs(skill)
        if not skill_tools:
            continue

        for agent in agents:
            agent_tools = _parse_agent_tools(agent.get("tools", ""))
            if "*" in agent_tools:
                continue  # wildcard grants everything

            for tool in skill_tools:
                if not _agent_has_tool(agent_tools, tool):
                    warnings.append(
                        {
                            "agent": agent.get("name", "?"),
                            "agent_kind": agent["_kind"],
                            "skill": skill.get("name", "?"),
                            "skill_kind": skill["_kind"],
                            "missing_tool": tool,
                        }
                    )

    return warnings


def check_cache_hygiene(
    home_dir: Path,
) -> list[dict[str, Any]]:
    """Inspect the plugin cache for hygiene issues.

    Two checks:

    * **stray_temp_git**: any directory directly inside
      ``<home>/.claude/plugins/cache/`` whose name starts with
      ``temp_git_``.
    * **duplicate_plugin_name**: the same plugin name appears under two
      or more marketplace directories.

    Args:
        home_dir: Path to the user home directory.

    Returns:
        A list of finding records, each with keys ``kind`` and
        ``detail``.
    """
    findings: list[dict[str, Any]] = []
    cache_root = home_dir / ".claude" / "plugins" / "cache"

    if not cache_root.is_dir():
        return findings

    # Collect all (marketplace, plugin_name) pairs
    plugin_marketplaces: dict[str, list[str]] = defaultdict(list)

    for entry in cache_root.iterdir():
        if not entry.is_dir():
            continue

        # Check for stray temp_git_* directories at cache root level
        if entry.name.startswith("temp_git_"):
            findings.append(
                {
                    "kind": "stray_temp_git",
                    "detail": (f"Stray clone leftover at cache root: {entry.name}"),
                    "path": str(entry),
                }
            )
            continue

        # This entry is a marketplace directory
        marketplace = entry.name
        for plugin_dir in entry.iterdir():
            if plugin_dir.is_dir():
                plugin_marketplaces[plugin_dir.name].append(marketplace)

    # Flag plugin names that appear in more than one marketplace
    for plugin_name, marketplaces in sorted(plugin_marketplaces.items()):
        if len(marketplaces) > 1:
            findings.append(
                {
                    "kind": "duplicate_plugin_name",
                    "detail": (
                        f"Plugin '{plugin_name}' found in multiple "
                        f"marketplaces: {', '.join(sorted(marketplaces))}"
                    ),
                    "plugin": plugin_name,
                    "marketplaces": sorted(marketplaces),
                }
            )

    return findings


# ---------------------------------------------------------------------------
# Internal helpers — source walking
# ---------------------------------------------------------------------------


def _walk_agents(
    directory: Path,
    kind: str,
    items: list[dict[str, Any]],
) -> None:
    """Append parsed agent items from *directory* to *items*.

    Args:
        directory: Directory containing ``*.md`` agent files.
        kind: The ``_kind`` string to assign (e.g. ``"custom-user"``).
        items: Accumulator list modified in-place.
    """
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.md")):
        fm = _parse_frontmatter(path)
        if fm is not None:
            fm["_kind"] = kind
            fm["_type"] = "agent"
            items.append(fm)


def _walk_skills(
    skills_root: Path,
    kind: str,
    items: list[dict[str, Any]],
) -> None:
    """Append parsed skill items from *skills_root*/*/SKILL.md to *items*.

    Args:
        skills_root: Parent directory; each subdirectory is a skill
            folder containing a SKILL.md.
        kind: The ``_kind`` string to assign.
        items: Accumulator list modified in-place.
    """
    if not skills_root.is_dir():
        return
    for path in sorted(skills_root.glob("*/SKILL.md")):
        fm = _parse_frontmatter(path)
        if fm is not None:
            fm["_kind"] = kind
            fm["_type"] = "skill"
            items.append(fm)


def _walk_plugin_cache(
    home_dir: Path,
    items: list[dict[str, Any]],
) -> None:
    """Walk the plugin cache and add items for the latest version only.

    For each ``(marketplace, plugin)`` pair under
    ``<home>/.claude/plugins/cache/``, picks the lexically greatest
    version directory and walks its agents and skills.

    Args:
        home_dir: User home directory.
        items: Accumulator list modified in-place.
    """
    cache_root = home_dir / ".claude" / "plugins" / "cache"
    if not cache_root.is_dir():
        return

    # Build a map of (marketplace, plugin) → latest version directory
    latest: dict[tuple[str, str], Path] = {}

    for marketplace_dir in sorted(cache_root.iterdir()):
        if not marketplace_dir.is_dir():
            continue
        if marketplace_dir.name.startswith("temp_git_"):
            continue

        marketplace = marketplace_dir.name
        for plugin_dir in sorted(marketplace_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            plugin_name = plugin_dir.name

            versions = sorted(v for v in plugin_dir.iterdir() if v.is_dir())
            if not versions:
                continue

            # Lexically greatest version
            latest_version_dir = versions[-1]
            key = (marketplace, plugin_name)

            # Keep the greatest across marketplaces (lexical)
            if key not in latest or (latest_version_dir.name > latest[key].name):
                latest[key] = latest_version_dir

    for (marketplace, plugin_name), version_dir in sorted(latest.items()):
        kind = f"plugin:{plugin_name}"
        _walk_agents(version_dir / "agents", kind=kind, items=items)
        _walk_skills(version_dir / "skills", kind=kind, items=items)


def _walk_claude_desktop(
    home_dir: Path,
    items: list[dict[str, Any]],
) -> None:
    """Walk Windows Claude Desktop skill-plugin SKILL.md files.

    Args:
        home_dir: User home directory.
        items: Accumulator list modified in-place.
    """
    desktop_root = (
        home_dir
        / "AppData"
        / "Roaming"
        / "Claude"
        / "local-agent-mode-sessions"
        / "skills-plugin"
    )
    if not desktop_root.is_dir():
        return
    for path in sorted(desktop_root.rglob("SKILL.md")):
        fm = _parse_frontmatter(path)
        if fm is not None:
            fm["_kind"] = "claude-desktop"
            fm["_type"] = "skill"
            items.append(fm)


# ---------------------------------------------------------------------------
# Internal helpers — frontmatter parsing
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Read *path* and extract YAML frontmatter fields.

    Handles only simple scalar ``key: value`` lines.  Multi-line values
    (e.g. YAML block scalars) are not supported; those lines are skipped.

    Args:
        path: Path to a Markdown file that may contain YAML frontmatter
            delimited by ``---`` fences.

    Returns:
        A dict with the parsed fields plus ``_path`` (str), or ``None``
        if the file cannot be read or has no frontmatter.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # Store the full text for body-level analysis
    _body_text = text

    match = re.match(r"---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None

    fm: dict[str, Any] = {"_path": str(path), "_body": _body_text}
    for line in match.group(1).splitlines():
        key_val = re.match(r"([\w-]+):\s*(.*)", line)
        if key_val:
            key = key_val.group(1)
            value = key_val.group(2).strip().strip('"').strip("'")
            fm[key] = value

    return fm


# ---------------------------------------------------------------------------
# Internal helpers — analysis
# ---------------------------------------------------------------------------


def _bigrams(text: str) -> set[tuple[str, str]]:
    """Return the set of adjacent word bigrams from *text*.

    Args:
        text: Input text (any case; punctuation is ignored).

    Returns:
        A set of ``(word_i, word_i+1)`` tuples (lowercased).
    """
    tokens = re.findall(r"\w+", text.lower())
    if len(tokens) < 2:
        return set()
    return set(zip(tokens, tokens[1:]))


def _jaccard_bigram(text_a: str, text_b: str) -> float:
    """Compute bigram Jaccard similarity between two text strings.

    Args:
        text_a: First description string.
        text_b: Second description string.

    Returns:
        A float in [0, 1]; 0.0 if either bigram set is empty.
    """
    set_a = _bigrams(text_a)
    set_b = _bigrams(text_b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _extract_skill_tool_refs(skill: dict[str, Any]) -> list[str]:
    """Extract tool references from a skill's body text.

    Scans for ``mcp__*`` identifiers, ``PowerShell``, and ``Bash``.

    Args:
        skill: A parsed skill item dict (must contain ``_body`` key).

    Returns:
        A deduplicated list of tool name strings found.
    """
    body = skill.get("_body", "")
    if not body:
        return []

    tools: set[str] = set()

    # mcp__ tool names
    for match in re.finditer(r"mcp__[\w]+(?:__[\w]+)*", body):
        tools.add(match.group(0))

    # Shell names
    if re.search(r"\bPowerShell\b", body):
        tools.add("PowerShell")
    if re.search(r"\bBash\b", body):
        tools.add("Bash")

    return sorted(tools)


def _parse_agent_tools(tools_str: str) -> set[str]:
    """Parse a comma-separated ``tools`` frontmatter value into a set.

    Args:
        tools_str: The raw ``tools`` string from the agent frontmatter.

    Returns:
        A set of individual tool name strings (stripped, lowercased for
        comparison, preserving ``*``).
    """
    if not tools_str:
        return set()
    if tools_str.strip() == "*":
        return {"*"}
    return {t.strip() for t in tools_str.split(",") if t.strip()}


def _agent_has_tool(agent_tools: set[str], tool: str) -> bool:
    """Return True if *tool* is covered by *agent_tools*.

    A partial prefix match is used for MCP tools: if the agent lists
    ``mcp__plugin_github_github__*`` and the skill uses
    ``mcp__plugin_github_github__list_pull_requests``, that counts.

    Args:
        agent_tools: Set of tool names from the agent's frontmatter.
        tool: The tool name extracted from the skill body.

    Returns:
        True if the agent grants access to the tool.
    """
    if "*" in agent_tools:
        return True
    for at in agent_tools:
        if at == tool:
            return True
        # Prefix wildcard for MCP namespace matching
        if at.endswith("*") and tool.startswith(at[:-1]):
            return True
    return False


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_markdown(
    items: list[dict[str, Any]],
    collisions: list[dict[str, Any]],
    overlaps: list[dict[str, Any]],
    tool_coupling: list[dict[str, Any]],
    cache_hygiene: list[dict[str, Any]],
) -> str:
    """Render the audit report as a markdown string.

    Args:
        items: All collected items.
        collisions: Output of :func:`find_collisions`.
        overlaps: Output of :func:`find_semantic_overlaps`.
        tool_coupling: Output of :func:`find_tool_coupling_issues`.
        cache_hygiene: Output of :func:`check_cache_hygiene`.

    Returns:
        Multi-line markdown string.
    """
    from collections import Counter

    lines: list[str] = []
    w = lines.append

    agents = [i for i in items if i["_type"] == "agent"]
    skills = [i for i in items if i["_type"] == "skill"]

    # ------------------------------------------------------------------ Title
    w("# Claude Config Audit")
    w("")

    # ------------------------------------------------------------ §1 Inventory
    w("## Inventory")
    w("")

    kind_counts = Counter(i["_kind"] for i in items)
    custom_user_agents = sum(1 for i in agents if i["_kind"] == "custom-user")
    custom_user_skills = sum(1 for i in skills if i["_kind"] == "custom-user")
    custom_proj_items = sum(1 for i in items if i["_kind"] == "custom-project")
    plugin_agents = sum(1 for i in agents if i["_kind"].startswith("plugin:"))
    plugin_skills = sum(1 for i in skills if i["_kind"].startswith("plugin:"))

    w(f"- Custom agents (user-scope): {custom_user_agents}")
    w(f"- Custom skills (user-scope): {custom_user_skills}")
    w(f"- Custom items (project-scope): {custom_proj_items}")
    w(f"- Plugin agents: {plugin_agents}")
    w(f"- Plugin skills: {plugin_skills}")
    w(f"- **Effective total: {len(agents)} agents / {len(skills)} skills**")
    w("")
    w("### By source")
    w("")
    w("| Source | Items |")
    w("|---|---|")
    for kind, count in kind_counts.most_common():
        w(f"| `{kind}` | {count} |")
    w("")

    # ------------------------------------------------ §2 Direct name collisions
    w("## Direct name collisions")
    w("")
    if not collisions:
        w("_None._")
    else:
        w("| Type | Name | Sources |")
        w("|---|---|---|")
        for col in collisions:
            sources_str = ", ".join(col["sources"])
            w(f"| {col['type']} | `{col['name']}` | {sources_str} |")
    w("")

    # ------------------------------------------ §3 Semantic overlaps (Jaccard)
    w("## Semantic overlaps (Jaccard ≥ 0.5)")
    w("")
    if not overlaps:
        w("_None._")
    else:
        w("| Type | A | B | Jaccard |")
        w("|---|---|---|---|")
        for ov in overlaps:
            na, nb = ov["names"]
            ka, kb = ov["kinds"]
            w(
                f"| {ov['type']} | `{na}` ({ka})"
                f" | `{nb}` ({kb}) | {ov['score']:.2f} |"
            )
    w("")

    # --------------------------------------- §4 Tool-coupling concerns
    w("## Tool-coupling concerns")
    w("")
    if not tool_coupling:
        w("_None._")
    else:
        w("| Agent | Skill | Missing tool |")
        w("|---|---|---|")
        for tc in tool_coupling:
            w(
                f"| `{tc['agent']}` ({tc['agent_kind']})"
                f" | `{tc['skill']}` ({tc['skill_kind']})"
                f" | `{tc['missing_tool']}` |"
            )
    w("")

    # --------------------------------------- §5 Cache hygiene
    w("## Cache hygiene findings")
    w("")
    if not cache_hygiene:
        w("_None._")
    else:
        w("| Kind | Detail |")
        w("|---|---|")
        for finding in cache_hygiene:
            w(f"| {finding['kind']} | {finding['detail']} |")
    w("")

    return "\n".join(lines)


def _render_json(
    items: list[dict[str, Any]],
    collisions: list[dict[str, Any]],
    overlaps: list[dict[str, Any]],
    tool_coupling: list[dict[str, Any]],
    cache_hygiene: list[dict[str, Any]],
) -> str:
    """Render the audit report as a JSON string.

    Args:
        items: All collected items.
        collisions: Output of :func:`find_collisions`.
        overlaps: Output of :func:`find_semantic_overlaps`.
        tool_coupling: Output of :func:`find_tool_coupling_issues`.
        cache_hygiene: Output of :func:`check_cache_hygiene`.

    Returns:
        JSON-encoded string with the top-level keys ``inventory``,
        ``collisions``, ``overlaps``, ``tool_coupling``, and
        ``cache_hygiene``.
    """
    agents = [i for i in items if i["_type"] == "agent"]
    skills = [i for i in items if i["_type"] == "skill"]

    from collections import Counter

    by_kind = dict(Counter(i["_kind"] for i in items))

    payload: dict[str, Any] = {
        "inventory": {
            "total_agents": len(agents),
            "total_skills": len(skills),
            "by_kind": by_kind,
        },
        "collisions": [
            {
                "type": c["type"],
                "name": c["name"],
                "sources": c["sources"],
            }
            for c in collisions
        ],
        "overlaps": overlaps,
        "tool_coupling": tool_coupling,
        "cache_hygiene": [
            {k: v for k, v in f.items() if k != "path"} for f in cache_hygiene
        ],
    }
    return json.dumps(payload, indent=2)
