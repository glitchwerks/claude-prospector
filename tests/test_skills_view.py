from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_JS = (
    _REPO_ROOT
    / "src"
    / "claude_prospector"
    / "static"
    / "views"
    / "skills.js"
)


def _source() -> str:
    return _SKILLS_JS.read_text(encoding="utf-8")


def test_skill_rows_iterate_the_union_population() -> None:
    source = _source()
    assert "new Set" in source
    assert "Object.keys(bySkill)" in source
    assert "Object.keys(adoption)" in source


def test_untracked_adoption_is_not_rendered_as_zero() -> None:
    source = _source()
    assert "const tracked = Boolean(adoptionInfo);" in source
    assert "tracked ? adoptionInfo.times_passed : null" in source
    assert "tracked ? adoptionInfo.times_invoked : null" in source
    assert "tracked ? adoptionInfo.adoption_rate : null" in source
    assert "formatUnknown" in source


def test_gap_detection_uses_the_actual_adoption_rate() -> None:
    source = _source()
    assert "row.adoptionRate === 0" in source
    assert "row.timesPassed > 0" in source


def test_target_agent_disclosure_is_labeled_and_escaped() -> None:
    source = _source()
    assert "target agent as recorded by the skill-tracker hook" in source.lower()
    assert "<details" in source
    assert "by_target_agent" in source
    assert "CP.esc(" in source


def test_filter_updates_only_the_results_wrapper() -> None:
    source = _source()
    assert 'id="skill-name-filter"' in source
    assert 'id="skill-results"' in source
    listener = re.search(
        r"skill-name-filter.*?addEventListener\(\s*['\"]input['\"]"
        r"(?P<body>.*?)\n\s*\}\);",
        source,
        re.DOTALL,
    )
    assert listener is not None
    assert "CP.matchesNameFilter(" in source
    assert "results.innerHTML" in listener.group("body")
    assert "root.innerHTML" not in listener.group("body")


def test_empty_and_adoption_unavailable_states_are_distinct() -> None:
    source = _source().lower()
    assert "no skill usage recorded" in source
    assert "adoption tracking unavailable" in source
    assert "skill-tracker" in source


def test_report_has_no_client_period_control() -> None:
    source = _source()
    assert "data-period=" not in source
