"""Tests for the audit subcommand.

Covers: inventory walk, plugin cache version dedup, direct name
collisions, Jaccard semantic overlaps, cache hygiene findings, JSON
output mode, and CLI smoke.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from claude_prospector.cli import audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_FM = dedent(
    """\
    ---
    name: {name}
    description: {description}
    tools: Bash, Read
    ---
    # Body
    """
)

_SKILL_FM = dedent(
    """\
    ---
    name: {name}
    description: {description}
    ---
    # Body
    """
)


def _write_agent(directory: Path, name: str, description: str = "") -> Path:
    """Write a minimal agent .md file to *directory*.

    Args:
        directory: Target directory (must exist).
        name: Agent name for the frontmatter ``name`` field.
        description: Optional description for the frontmatter.

    Returns:
        The path to the written file.
    """
    path = directory / f"{name}.md"
    path.write_text(
        _AGENT_FM.format(name=name, description=description),
        encoding="utf-8",
    )
    return path


def _write_skill(parent: Path, name: str, description: str = "") -> Path:
    """Write a minimal SKILL.md under *parent*/<name>/SKILL.md.

    Args:
        parent: Parent skills directory.
        name: Skill name; used for both the directory name and frontmatter.
        description: Optional description.

    Returns:
        Path to the written SKILL.md.
    """
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        _SKILL_FM.format(name=name, description=description),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# 1. Inventory walk
# ---------------------------------------------------------------------------


def test_inventory_walk_custom_user(tmp_path: Path) -> None:
    """Items in ~/.claude/agents and ~/.claude/skills appear with correct
    _kind and _type values."""
    home = tmp_path / "home"
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    skills_dir = home / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    _write_agent(agents_dir, "code-writer", "Writes production code")
    _write_skill(skills_dir, "python", "Python coding standard skill")

    items = audit.collect_items(home_dir=home, project_dir=tmp_path / "proj")

    agent_items = [i for i in items if i["_type"] == "agent"]
    skill_items = [i for i in items if i["_type"] == "skill"]

    assert len(agent_items) == 1
    assert agent_items[0]["_kind"] == "custom-user"
    assert agent_items[0]["name"] == "code-writer"

    assert len(skill_items) == 1
    assert skill_items[0]["_kind"] == "custom-user"
    assert skill_items[0]["name"] == "python"


def test_inventory_walk_project_scope(tmp_path: Path) -> None:
    """Items under <project>/.claude/ appear with _kind == 'custom-project'."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    proj_agents = proj / ".claude" / "agents"
    proj_agents.mkdir(parents=True)

    _write_agent(proj_agents, "project-agent", "A project-scoped agent")

    items = audit.collect_items(home_dir=home, project_dir=proj)
    proj_items = [i for i in items if i["_kind"] == "custom-project"]

    assert len(proj_items) == 1
    assert proj_items[0]["name"] == "project-agent"
    assert proj_items[0]["_type"] == "agent"


# ---------------------------------------------------------------------------
# 2. Plugin cache version dedup
# ---------------------------------------------------------------------------


def test_plugin_cache_picks_latest_version_only(tmp_path: Path) -> None:
    """Only the lexically-greatest version per (marketplace, plugin) is used."""
    home = tmp_path / "home"
    cache_root = home / ".claude" / "plugins" / "cache"

    for version in ("0.1.0", "0.2.0", "1.0.0"):
        skill_dir = (
            cache_root / "glitchwerks" / "my-plugin" / version / "skills" / "my-skill"
        )
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            _SKILL_FM.format(
                name=f"my-skill-{version}",
                description=f"Skill version {version}",
            ),
            encoding="utf-8",
        )

    items = audit.collect_items(home_dir=home, project_dir=tmp_path / "proj")
    skill_items = [i for i in items if i["_type"] == "skill"]

    # Only 1.0.0 should be picked
    assert len(skill_items) == 1
    assert "1.0.0" in skill_items[0]["name"]


def test_plugin_cache_multiple_plugins_deduped_independently(
    tmp_path: Path,
) -> None:
    """Each (marketplace, plugin) pair is deduped independently."""
    home = tmp_path / "home"
    cache_root = home / ".claude" / "plugins" / "cache"

    for plugin_name, versions in [
        ("plugin-a", ("0.5.0", "1.0.0")),
        ("plugin-b", ("0.1.0", "0.9.0")),
    ]:
        for version in versions:
            skill_dir = (
                cache_root
                / "glitchwerks"
                / plugin_name
                / version
                / "skills"
                / f"skill-{plugin_name}"
            )
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                _SKILL_FM.format(
                    name=f"skill-{plugin_name}-{version}",
                    description="A skill",
                ),
                encoding="utf-8",
            )

    items = audit.collect_items(home_dir=home, project_dir=tmp_path / "proj")
    skill_items = [i for i in items if i["_type"] == "skill"]

    # One latest version per plugin = 2 total
    assert len(skill_items) == 2
    names = [i["name"] for i in skill_items]
    assert any("1.0.0" in n for n in names)
    assert any("0.9.0" in n for n in names)


# ---------------------------------------------------------------------------
# 3. Direct collisions
# ---------------------------------------------------------------------------


def test_direct_collisions_detected(tmp_path: Path) -> None:
    """Two agents with the same name from different sources produce exactly
    one collision entry."""
    home = tmp_path / "home"
    agents_user = home / ".claude" / "agents"
    agents_user.mkdir(parents=True)

    proj = tmp_path / "proj"
    agents_proj = proj / ".claude" / "agents"
    agents_proj.mkdir(parents=True)

    _write_agent(agents_user, "my-agent", "User-scope agent")
    _write_agent(agents_proj, "my-agent", "Project-scope agent")

    items = audit.collect_items(home_dir=home, project_dir=proj)
    collisions = audit.find_collisions(items)

    assert len(collisions) == 1
    col = collisions[0]
    assert col["type"] == "agent"
    assert col["name"] == "my-agent"
    assert len(col["sources"]) == 2


def test_no_false_collision_different_names(tmp_path: Path) -> None:
    """Agents with different names do not produce a collision."""
    home = tmp_path / "home"
    agents_user = home / ".claude" / "agents"
    agents_user.mkdir(parents=True)

    _write_agent(agents_user, "agent-alpha", "Alpha")
    _write_agent(agents_user, "agent-beta", "Beta")

    items = audit.collect_items(home_dir=home, project_dir=tmp_path / "proj")
    collisions = audit.find_collisions(items)

    assert collisions == []


# ---------------------------------------------------------------------------
# 4. Jaccard semantic overlaps
# ---------------------------------------------------------------------------


def test_semantic_overlap_above_threshold(tmp_path: Path) -> None:
    """Two skills with heavily overlapping descriptions surface as an overlap."""
    home = tmp_path / "home"
    skills_dir = home / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    # Very similar descriptions — should score >= 0.5
    desc_a = "Write clean production Python code following PEP8 standards"
    desc_b = "Write clean production Python code following PEP8 coding standards"
    _write_skill(skills_dir, "python-a", desc_a)
    _write_skill(skills_dir, "python-b", desc_b)

    items = audit.collect_items(home_dir=home, project_dir=tmp_path / "proj")
    overlaps = audit.find_semantic_overlaps(items, threshold=0.5)

    assert len(overlaps) == 1
    ov = overlaps[0]
    assert ov["score"] >= 0.5
    assert set(ov["names"]) == {"python-a", "python-b"}


def test_semantic_overlap_below_threshold_not_surfaced(tmp_path: Path) -> None:
    """Two skills with unrelated descriptions are not flagged as an overlap."""
    home = tmp_path / "home"
    skills_dir = home / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    _write_skill(skills_dir, "python", "Write Python code PEP8 production")
    _write_skill(
        skills_dir,
        "skyrim",
        "Craft Skyrim papyrus scripts for modding",
    )

    items = audit.collect_items(home_dir=home, project_dir=tmp_path / "proj")
    overlaps = audit.find_semantic_overlaps(items, threshold=0.5)

    assert overlaps == []


def test_semantic_overlap_no_cross_type(tmp_path: Path) -> None:
    """An agent and a skill with similar descriptions are NOT flagged
    (cross-type pairs are excluded)."""
    home = tmp_path / "home"
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    skills_dir = home / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    desc = "Write clean production Python code following PEP8 coding standards"
    _write_agent(agents_dir, "python-agent", desc)
    _write_skill(skills_dir, "python-skill", desc)

    items = audit.collect_items(home_dir=home, project_dir=tmp_path / "proj")
    overlaps = audit.find_semantic_overlaps(items, threshold=0.5)

    # Cross-type pairs must not appear
    assert overlaps == []


# ---------------------------------------------------------------------------
# 5. Cache hygiene
# ---------------------------------------------------------------------------


def test_cache_hygiene_temp_git_dirs(tmp_path: Path) -> None:
    """A temp_git_* directory at the cache root is flagged."""
    home = tmp_path / "home"
    cache_root = home / ".claude" / "plugins" / "cache"
    cache_root.mkdir(parents=True)
    stray = cache_root / "temp_git_abc123"
    stray.mkdir()

    findings = audit.check_cache_hygiene(home_dir=home)

    assert any("temp_git_abc123" in f["detail"] for f in findings)
    assert any(f["kind"] == "stray_temp_git" for f in findings)


def test_cache_hygiene_same_plugin_in_two_marketplaces(tmp_path: Path) -> None:
    """The same plugin name in two different marketplace directories is flagged."""
    home = tmp_path / "home"
    cache_root = home / ".claude" / "plugins" / "cache"

    mk1_plugin = cache_root / "glitchwerks" / "my-plugin" / "1.0.0"
    mk1_plugin.mkdir(parents=True)
    mk2_plugin = cache_root / "some-other-market" / "my-plugin" / "0.5.0"
    mk2_plugin.mkdir(parents=True)

    findings = audit.check_cache_hygiene(home_dir=home)

    assert any(f["kind"] == "duplicate_plugin_name" for f in findings)
    dup_finding = next(f for f in findings if f["kind"] == "duplicate_plugin_name")
    assert "my-plugin" in dup_finding["detail"]


def test_cache_hygiene_no_stray_dirs(tmp_path: Path) -> None:
    """A clean cache root produces no cache-hygiene findings."""
    home = tmp_path / "home"
    cache_root = home / ".claude" / "plugins" / "cache"
    (cache_root / "glitchwerks" / "my-plugin" / "1.0.0").mkdir(parents=True)

    findings = audit.check_cache_hygiene(home_dir=home)

    assert findings == []


# ---------------------------------------------------------------------------
# 6. JSON output mode
# ---------------------------------------------------------------------------


def test_json_output_has_required_keys(tmp_path: Path) -> None:
    """--format json emits a JSON object with the required top-level keys."""
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "proj"

    result = audit.run_audit(
        home_dir=home,
        project_dir=proj,
        output_format="json",
    )

    parsed = json.loads(result)
    required_keys = {
        "inventory",
        "collisions",
        "overlaps",
        "tool_coupling",
        "cache_hygiene",
    }
    assert required_keys.issubset(set(parsed.keys()))


def test_json_output_inventory_counts(tmp_path: Path) -> None:
    """JSON inventory counts match the items actually collected."""
    home = tmp_path / "home"
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    skills_dir = home / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    _write_agent(agents_dir, "agent-one", "An agent")
    _write_skill(skills_dir, "skill-one", "A skill")

    result = audit.run_audit(
        home_dir=home,
        project_dir=tmp_path / "proj",
        output_format="json",
    )
    parsed = json.loads(result)
    inv = parsed["inventory"]

    assert inv["total_agents"] == 1
    assert inv["total_skills"] == 1


# ---------------------------------------------------------------------------
# 7. CLI smoke — subprocess
# ---------------------------------------------------------------------------


def test_cli_help_exits_zero() -> None:
    """python -m claude_prospector audit --help exits 0 and mentions 'audit'."""
    result = subprocess.run(
        [sys.executable, "-m", "claude_prospector", "audit", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "audit" in result.stdout.lower()


def test_audit_subcommand_listed_in_main_help() -> None:
    """python -m claude_prospector --help lists the audit subcommand."""
    result = subprocess.run(
        [sys.executable, "-m", "claude_prospector", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "audit" in result.stdout.lower()
