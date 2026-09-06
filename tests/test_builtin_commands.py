"""Behavior tests for the packaged Claude Code command catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_prospector import builtin_commands
from claude_prospector.builtin_commands import load_command_catalog


def test_catalog_classifies_builtins_skills_workflows_and_unknowns() -> None:
    """Catalog categories must keep non-built-ins out of usage totals."""
    catalog = load_command_catalog()

    assert catalog.available is True
    assert catalog.classify("/compact") == "builtin"
    assert catalog.classify("/fork") == "builtin"
    assert catalog.classify("/batch") == "bundled_skill"
    assert catalog.classify("/doctor") == "bundled_skill"
    assert catalog.classify("/checkup") == "bundled_skill"
    assert catalog.classify("/deep-research") == "workflow"
    assert catalog.classify("/project-review") == "unclassified"


def test_catalog_exposes_a_dated_official_source() -> None:
    """Users must be able to audit where the classification came from."""
    catalog = load_command_catalog()

    assert catalog.source_url == "https://code.claude.com/docs/en/commands"
    assert catalog.retrieved_at == "2026-09-06"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "source_url": "https://code.claude.com/docs/en/commands",
            "retrieved_at": "2026-09-06",
            "builtins": "/fork",
            "bundled_skills": [],
            "workflows": [],
        },
        {
            "source_url": None,
            "retrieved_at": "2026-09-06",
            "builtins": ["/fork"],
            "bundled_skills": [],
            "workflows": [],
        },
        {
            "source_url": "https://code.claude.com/docs/en/commands",
            "retrieved_at": "2026-09-06",
            "builtins": ["/fork"],
            "bundled_skills": ["/fork"],
            "workflows": [],
        },
        {
            "source_url": "https://code.claude.com/docs/en/commands",
            "retrieved_at": "2026-09-06",
            "builtins": ["fork without slash"],
            "bundled_skills": [],
            "workflows": [],
        },
    ],
)
def test_malformed_catalogs_fall_back_to_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    """Invalid catalog structure cannot produce misleading classifications."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "claude-code-commands.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    monkeypatch.setattr(builtin_commands.resources, "files", lambda _: tmp_path)
    load_command_catalog.cache_clear()

    try:
        catalog = load_command_catalog()
    finally:
        load_command_catalog.cache_clear()

    assert catalog.available is False
    assert catalog.source_url is None
    assert catalog.classify("/fork") == "unclassified"


def test_missing_catalog_falls_back_to_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing package resource degrades without breaking the dashboard."""
    monkeypatch.setattr(builtin_commands.resources, "files", lambda _: tmp_path)
    load_command_catalog.cache_clear()

    try:
        catalog = load_command_catalog()
    finally:
        load_command_catalog.cache_clear()

    assert catalog.available is False
