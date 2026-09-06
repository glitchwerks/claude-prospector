from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_JS = _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "skills.js"
_CP_UTILS_JS = _REPO_ROOT / "src" / "claude_prospector" / "static" / "cp-utils.js"


def _source() -> str:
    return _SKILLS_JS.read_text(encoding="utf-8")


def _render_skills(tmp_path: Path, payload: dict[str, object]) -> dict[str, str]:
    """Execute the real Skills renderer against a minimal DOM boundary."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; JavaScript execution test skipped")

    runner = tmp_path / "skills-render-check.js"
    runner.write_text(
        """
const fs = require('fs');
const vm = require('vm');
global.window = { DATA: JSON.parse(fs.readFileSync(0, 'utf8')) };
global.document = {
  getElementById: () => null,
  createElement: () => ({ id: '', textContent: '' }),
  head: { appendChild: () => {} },
};
vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'));
global.CP = window.CP;
vm.runInThisContext(fs.readFileSync(process.argv[3], 'utf8'));

const filterInput = { value: '', addEventListener: () => {} };
const results = { innerHTML: '' };
const root = {
  innerHTML: '',
  classList: { add: () => {} },
  querySelector: (selector) => (
    selector === '#skill-name-filter' ? filterInput : results
  ),
};
window.renderSkills(root);
process.stdout.write(JSON.stringify({
  root: root.innerHTML,
  results: results.innerHTML,
}));
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(runner), str(_CP_UTILS_JS), str(_SKILLS_JS)],
        input=json.dumps(payload),
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(completed.stdout)


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


@pytest.mark.parametrize(
    ("by_mcp_usage", "expected", "unexpected"),
    [
        ({}, "dashboard CLI window", "all time"),
        ({"window": {"start": None, "end": None}}, "all time", "dashboard CLI window"),
        (
            {"window": {"start": "2026-09-01", "end": "2026-09-05"}},
            "2026",
            "dashboard CLI window",
        ),
    ],
)
def test_time_basis_distinguishes_missing_unbounded_and_bounded_metadata(
    tmp_path: Path,
    by_mcp_usage: dict[str, object],
    expected: str,
    unexpected: str,
) -> None:
    """Missing metadata must not be presented as explicitly unbounded."""
    rendered = _render_skills(
        tmp_path,
        {
            "by_skill": {"python": {"invocation_count": 1, "total_tokens": 42}},
            "by_skill_adoption": {},
            "by_mcp_usage": by_mcp_usage,
        },
    )

    assert expected in rendered["root"]
    assert unexpected not in rendered["root"]


def test_prototype_named_skills_use_only_own_source_entries(tmp_path: Path) -> None:
    """Inherited properties cannot fabricate invocation or adoption data."""
    rendered = _render_skills(
        tmp_path,
        {
            "by_skill": {
                "constructor": {"invocation_count": 1, "total_tokens": 42},
            },
            "by_skill_adoption": {
                "__proto__": {
                    "times_passed": 2,
                    "times_invoked": 1,
                    "adoption_rate": 0.5,
                    "by_target_agent": {},
                },
            },
            "by_mcp_usage": {"window": {"start": None, "end": None}},
        },
    )["results"]

    constructor_row = re.search(
        r'<tr>\s*<td class="skill-name">constructor.*?</tr>',
        rendered,
        re.DOTALL,
    )
    proto_row = re.search(
        r'<tr>\s*<td class="skill-name">__proto__.*?</tr>',
        rendered,
        re.DOTALL,
    )
    assert constructor_row is not None
    assert proto_row is not None
    constructor_text = re.sub(r"\s+", " ", constructor_row.group(0))
    proto_text = re.sub(r"\s+", " ", proto_row.group(0))
    assert ">1</td> <td>42</td>" in constructor_text
    assert constructor_text.count('class="skill-unknown"') == 3
    assert ">n/a</td>" in constructor_text
    assert '>0</td> <td>0</td> <td class="">2</td>' in proto_text
    assert '>1</td> <td class="">50%</td>' in proto_text


def test_unavailable_adoption_omits_unmeasured_pass_summary(tmp_path: Path) -> None:
    """Missing pass observations must not be summarized as measured zero."""
    rendered = _render_skills(
        tmp_path,
        {
            "by_skill": {"python": {"invocation_count": 1, "total_tokens": 42}},
            "by_skill_adoption": {},
            "by_mcp_usage": {},
        },
    )["results"]

    assert "Adoption tracking unavailable" in rendered
    assert "passed to agents" not in rendered
    assert "recorded pass events" not in rendered


def test_available_adoption_labels_recorded_pass_events(tmp_path: Path) -> None:
    """Available hook counts are labeled as recorded observations."""
    rendered = _render_skills(
        tmp_path,
        {
            "by_skill": {},
            "by_skill_adoption": {
                "python": {
                    "times_passed": 2,
                    "times_invoked": 1,
                    "adoption_rate": 0.5,
                    "by_target_agent": {},
                },
            },
            "by_mcp_usage": {},
        },
    )["results"]

    assert "<strong>2</strong> recorded pass events" in rendered


def test_builtin_command_report_renders_counts_and_unclassified_names(
    tmp_path: Path,
) -> None:
    """Built-ins and unknown commands remain visibly distinct."""
    rendered = _render_skills(
        tmp_path,
        {
            "by_skill": {},
            "by_skill_adoption": {},
            "by_mcp_usage": {},
            "by_command_usage": {
                "classification": {
                    "available": True,
                    "source_url": "https://code.claude.com/docs/en/commands",
                    "retrieved_at": "2026-09-06",
                },
                "by_command": {
                    "/fork": {"invocation_count": 3, "sessions_used_in": 2},
                },
                "unclassified": {
                    "/project-review": {
                        "invocation_count": 1,
                        "sessions_used_in": 1,
                    },
                },
            },
        },
    )["root"]

    assert "Built-in Commands" in rendered
    assert "/fork" in rendered
    assert ">3</td>" in rendered
    assert ">2</td>" in rendered
    assert "/project-review" in rendered
    assert "not counted as built-ins" in rendered
    assert "2026-09-06" in rendered


def test_builtin_command_report_has_empty_and_unavailable_states(
    tmp_path: Path,
) -> None:
    """No observations and no catalog are reported differently."""
    empty = _render_skills(
        tmp_path,
        {
            "by_skill": {},
            "by_skill_adoption": {},
            "by_mcp_usage": {},
            "by_command_usage": {
                "classification": {
                    "available": True,
                    "source_url": "https://code.claude.com/docs/en/commands",
                    "retrieved_at": "2026-09-06",
                },
                "by_command": {},
                "unclassified": {},
            },
        },
    )["root"]
    unavailable = _render_skills(
        tmp_path,
        {
            "by_skill": {},
            "by_skill_adoption": {},
            "by_mcp_usage": {},
            "by_command_usage": {},
        },
    )["root"]

    assert "No manual built-in command usage recorded" in empty
    assert "Command classification unavailable" in unavailable


def test_builtin_command_names_are_html_escaped(tmp_path: Path) -> None:
    """Transcript-derived unknown names cannot inject dashboard markup."""
    rendered = _render_skills(
        tmp_path,
        {
            "by_skill": {},
            "by_skill_adoption": {},
            "by_mcp_usage": {},
            "by_command_usage": {
                "classification": {"available": True},
                "by_command": {},
                "unclassified": {
                    "/</code><script>alert(1)</script>": {
                        "invocation_count": 1,
                        "sessions_used_in": 1,
                    },
                },
            },
        },
    )["root"]

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


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


def test_target_agent_disclosure_reads_structured_passed_and_invoked_counts() -> None:
    source = _source()
    assert "const passed = agentInfo.passed;" in source
    assert "const invoked = agentInfo.invoked;" in source
    assert "Passed: ${CP.esc(CP.fmtTokens(passed))}" in source
    assert "Invoked: ${CP.esc(CP.fmtTokens(invoked))}" in source


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


def test_skills_tab_is_inlined_and_wired(tmp_path: Path) -> None:
    output = tmp_path / "dashboard.html"
    render(AggregateResult(), output_path=output, open_browser=False)
    html = output.read_text(encoding="utf-8")
    assert 'data-view="skills"' in html
    assert "window.renderSkills" in html
    assert "skills:" in html
    assert "renderSkills(_container)" in html


def test_breakdown_card_points_to_the_full_report() -> None:
    source = (
        _REPO_ROOT
        / "src"
        / "claude_prospector"
        / "static"
        / "views"
        / "layout-b-diag.js"
    ).read_text(encoding="utf-8")
    assert "skill: { q: '', sort: 'use' }" not in source
    assert "${allSkills.length} invoked" in source
    assert "Open full Skills report" in source
    assert "economy:switch-view" in source
    assert "view: 'skills'" in source
