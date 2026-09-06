# Skill Usage Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a searchable top-level Skills dashboard report that exposes the union of invocation and adoption data, including adoption gaps and per-target-agent disclosures.

**Architecture:** Keep the change in the existing presentation layer because `renderer.py` already places `by_skill` and `by_skill_adoption` in `window.DATA` (`src/claude_prospector/renderer.py:L87-L99`; `docs/superpowers/specs/skill-usage-report.md:L38-L52`). Add one isolated `skills.js` renderer, wire it through the existing offline-inline shell, and preserve the existing Breakdown card as a compact pointer. Consolidate the three name filters behind `CP.matchesNameFilter` as approved in issue #296 comment `5559494713`.

**Tech Stack:** Python 3.12, pytest, vanilla JavaScript, Jinja2, setuptools package data, `uv` (`CLAUDE.md:L24-L48`; `pyproject.toml:L21-L26`).

**Spec:** `docs/superpowers/specs/skill-usage-report.md`

## Global Constraints

- Work only on issue #296; built-in command reporting remains issue #298 (`docs/superpowers/specs/skill-usage-report.md:L38-L52`; #298).
- Render exactly the union of `by_skill` and `by_skill_adoption`; absence from adoption tracking must display as unknown, not zero (`docs/superpowers/specs/skill-usage-report.md:L142-L182`).
- Treat `by_target_agent` labels as hook-recorded target-agent names and never join them to full `by_agent` paths (`docs/superpowers/specs/skill-usage-report.md:L92-L105`).
- Escape every transcript- or hook-derived string at its HTML sink with `CP.esc` (`docs/superpowers/specs/skill-usage-report.md:L187-L201`; `src/claude_prospector/static/cp-utils.js:L383-L396`).
- Do not add client-side period controls or aggregation fields; state the server-side CLI-window basis in copy (`docs/superpowers/specs/skill-usage-report.md:L107-L120`, `L212-L215`).
- Keep filter focus by replacing only the results wrapper's `innerHTML` on input (`docs/superpowers/specs/skill-usage-report.md:L217-L227`; `src/claude_prospector/static/views/mcp-usage.js:L584-L611`).
- Verify both empty states, the six-tab narrow layout, JavaScript syntax, the complete Python suite, both Ruff gates, and wheel contents (`docs/superpowers/specs/skill-usage-report.md:L203-L245`, `L265-L311`, `L474-L510`; `CLAUDE.md:L38-L55`).

---

### Task 1: Consolidate the name-filter predicate

**Files:**
- Modify: `src/claude_prospector/static/cp-utils.js:51-67,383-396`
- Modify: `src/claude_prospector/static/views/agents.js:3-8,34-40`
- Modify: `src/claude_prospector/static/views/mcp-usage.js:63-75,500-557`
- Modify: `tests/test_agent_search_view.py:72-109`
- Modify: `tests/test_mcp_usage_view_name_filter.py:44-90,200-249`

**Interfaces:**
- Produces: `CP.matchesNameFilter(name, query) -> boolean`, a case-insensitive substring match that stringifies and trims both operands.
- Consumes: Existing `window.CP` export object and the Agents/MCP call sites (`src/claude_prospector/static/cp-utils.js:L383-L396`; `src/claude_prospector/static/views/agents.js:L3-L8`; `src/claude_prospector/static/views/mcp-usage.js:L63-L75`).

- [ ] **Step 1: Write failing shared-helper regression tests**

Add assertions that freeze the shared contract and reject private copies:

```python
def test_shared_name_filter_helper_is_exported_and_consumed() -> None:
    cp_source = _CP_UTILS_JS.read_text(encoding="utf-8")
    agents_source = _read_agents_js_source()
    mcp_source = _MCP_USAGE_JS.read_text(encoding="utf-8")

    assert "function matchesNameFilter(name, query)" in cp_source
    assert "matchesNameFilter," in cp_source
    assert "function matchesAgentFilter(" not in agents_source
    assert "function matchesNameFilter(" not in mcp_source
    assert "CP.matchesNameFilter(" in agents_source
    assert "CP.matchesNameFilter(" in mcp_source
```

Update `tests/test_mcp_usage_view_name_filter.py` so its predicate-body test reads `_CP_UTILS_JS` and its call-site assertions expect `CP.matchesNameFilter(...)`. Keep the GUID and dormant-server composition assertions unchanged because the migration is behavior-preserving (issue #296 comment `5559494713`; `tests/test_mcp_usage_view_name_filter.py:L31-L36`).

- [ ] **Step 2: Run the focused tests and verify they fail for the missing export**

Run:

```bash
uv run pytest -q tests/test_agent_search_view.py tests/test_mcp_usage_view_name_filter.py
```

Expected: FAIL because `CP.matchesNameFilter` is not defined or consumed.

- [ ] **Step 3: Add the shared helper and migrate both consumers**

Add to `cp-utils.js` before its export block:

```javascript
function matchesNameFilter(name, query) {
  const normalizedName = String(name).toLowerCase();
  const normalizedQuery = String(query).trim().toLowerCase();
  return normalizedName.includes(normalizedQuery);
}
```

Export it alongside the existing shared sink helpers:

```javascript
esc, agentLeaf, matchesNameFilter,
```

Delete `matchesAgentFilter` from `agents.js` and change its row filter to:

```javascript
.filter(([name]) => CP.matchesNameFilter(name, state.query))
```

Delete the local `matchesNameFilter` declaration from `mcp-usage.js`. Replace its server- and method-name calls with `CP.matchesNameFilter(name, query)`. Keep the listener's current query normalization; the shared helper tolerates both normalized and raw queries (`src/claude_prospector/static/views/mcp-usage.js:L606-L611`).

- [ ] **Step 4: Run focused tests and JavaScript syntax checks**

Run:

```bash
uv run pytest -q tests/test_agent_search_view.py tests/test_mcp_usage_view_name_filter.py
node --check src/claude_prospector/static/cp-utils.js
node --check src/claude_prospector/static/views/agents.js
node --check src/claude_prospector/static/views/mcp-usage.js
```

Expected: all tests and syntax checks pass.

- [ ] **Step 5: Commit the behavior-preserving consolidation**

```bash
git add src/claude_prospector/static/cp-utils.js src/claude_prospector/static/views/agents.js src/claude_prospector/static/views/mcp-usage.js tests/test_agent_search_view.py tests/test_mcp_usage_view_name_filter.py
git commit -m "refactor: share dashboard name filtering"
```

---

### Task 2: Build the Skills report test-first

**Files:**
- Create: `src/claude_prospector/static/views/skills.js`
- Create: `tests/test_skills_view.py`

**Interfaces:**
- Produces: `window.renderSkills(root) -> undefined`.
- Consumes: `window.DATA.by_skill`, `window.DATA.by_skill_adoption`, `window.DATA.by_mcp_usage.window`, `CP.matchesNameFilter`, `CP.esc`, and `CP.fmtTokens` (`src/claude_prospector/renderer.py:L87-L99`; `docs/superpowers/specs/skill-usage-report.md:L142-L261`).

- [ ] **Step 1: Create failing source-containment tests**

Create `tests/test_skills_view.py` with repository-path helpers and these contract tests:

```python
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_JS = (
    _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "skills.js"
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
```

These tests follow the repository's source-containment convention (`docs/superpowers/specs/skill-usage-report.md:L236-L245`; `tests/test_mcp_usage_view_name_filter.py:L11-L36`).

- [ ] **Step 2: Run the new test file and verify the missing-view failure**

Run:

```bash
uv run pytest -q tests/test_skills_view.py
```

Expected: FAIL with `FileNotFoundError` for `views/skills.js`.

- [ ] **Step 3: Implement the union data model and formatters**

In `skills.js`, use an isolated IIFE and build row objects with explicit nulls for untracked adoption:

```javascript
(function () {
  function skillRows() {
    const bySkill = window.DATA.by_skill || {};
    const adoption = window.DATA.by_skill_adoption || {};
    const names = [...new Set([
      ...Object.keys(bySkill),
      ...Object.keys(adoption),
    ])];
    return names.map(name => {
      const invocationInfo = bySkill[name] || null;
      const adoptionInfo = adoption[name] || null;
      const tracked = Boolean(adoptionInfo);
      return {
        name,
        invocations: invocationInfo ? invocationInfo.invocation_count : 0,
        totalTokens: invocationInfo ? invocationInfo.total_tokens : 0,
        timesPassed: tracked ? adoptionInfo.times_passed : null,
        timesInvoked: tracked ? adoptionInfo.times_invoked : null,
        adoptionRate: tracked ? adoptionInfo.adoption_rate : null,
        byTargetAgent: tracked ? (adoptionInfo.by_target_agent || {}) : {},
      };
    });
  }

  function formatUnknown(value) {
    return value === null ? '—' : CP.fmtTokens(value);
  }

  function formatRate(value) {
    return value === null ? 'n/a' : `${Math.round(value * 100)}%`;
  }
```

Sort rows by invocation count descending, then passed count descending, then name. Filter names with `CP.matchesNameFilter(row.name, query)`. Define adoption-gap rows only as `row.timesPassed > 0 && row.adoptionRate === 0`, preserving the independently filtered data semantics (`docs/superpowers/specs/skill-usage-report.md:L144-L182`).

- [ ] **Step 4: Implement the report markup, disclosures, and empty states**

Render these stable elements:

```javascript
<section class="skills-view">
  <div class="skills-toolbar">
    <div>
      <h1>Skill Usage</h1>
      <p>${timeBasisLine(window.DATA.by_mcp_usage?.window || {})}</p>
    </div>
    <input id="skill-name-filter" type="search"
      placeholder="Search skill names"
      aria-label="Search skills by name">
  </div>
  <div id="skill-results" aria-live="polite"></div>
</section>
```

The result renderer must include:

- counts labeled “skills invoked” and “passed to agents”;
- an adoption-gap callout listing escaped zero-rate skill names;
- columns for Skill, Invocations, Tokens, Times passed, Times invoked, and Adoption;
- `—`/`n/a` for untracked adoption fields;
- a footnote stating that transcript invocations and hook-correlated times-invoked are different measurements;
- a `<details>` disclosure per tracked skill with the exact label “Target agent as recorded by the skill-tracker hook”; and
- distinct copy for “No skill usage recorded” versus “Adoption tracking unavailable — enable the skill-tracker PreToolUse hook.”

Inside the input listener, assign only the results wrapper:

```javascript
filterInput.addEventListener('input', function () {
  state.query = filterInput.value;
  results.innerHTML = renderResults(state.query);
});
```

Expose the shell entry point:

```javascript
window.renderSkills = renderSkills;
})();
```

- [ ] **Step 5: Run the view tests and syntax check**

Run:

```bash
uv run pytest -q tests/test_skills_view.py
node --check src/claude_prospector/static/views/skills.js
```

Expected: all tests and syntax checks pass.

- [ ] **Step 6: Commit the isolated view**

```bash
git add src/claude_prospector/static/views/skills.js tests/test_skills_view.py
git commit -m "feat: add skill usage report view"
```

---

### Task 3: Wire the Skills tab and retain the compact Breakdown pointer

**Files:**
- Modify: `src/claude_prospector/renderer.py:115-127`
- Modify: `src/claude_prospector/templates/dashboard.html:296-379`
- Modify: `src/claude_prospector/static/views/layout-b-diag.js:986,1033-1077,1175-1182`
- Modify: `tests/test_skills_view.py`
- Modify: `tests/test_agent_search_view.py:393-422`
- Modify: `tests/test_phase2_shell.py:341-347`
- Modify: `tests/test_phase3_views.py:54-188,196-233`

**Interfaces:**
- Consumes: `window.renderSkills(root)` from Task 2.
- Produces: renderer template variable `skills_js`, `data-view="skills"`, `_VIEW_SUBS.skills`, an explicit Skills dispatch branch, and a Breakdown CTA that emits `economy:switch-view` with `{view: 'skills'}`.

- [ ] **Step 1: Add failing shell and card tests**

Extend `tests/test_skills_view.py` with rendered-HTML assertions:

```python
from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render


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
    assert "invoked" in source
    assert "Open full Skills report" in source
    assert "economy:switch-view" in source
    assert "view: 'skills'" in source
```

Update the exhaustive view set in `tests/test_agent_search_view.py` to:

```python
assert view_names == {"basic", "detail", "advanced", "mcp", "agents", "skills"}
```

Add `skills.js` disk/access/content checks to `tests/test_phase3_views.py` and assert `window.renderSkills` is present in rendered HTML. Add a `CP.matchesNameFilter` inline-content assertion to `tests/test_phase2_shell.py` so packaging cannot omit the new shared helper.

- [ ] **Step 2: Run integration tests and verify the missing shell wiring**

Run:

```bash
uv run pytest -q tests/test_skills_view.py tests/test_agent_search_view.py tests/test_phase2_shell.py tests/test_phase3_views.py
```

Expected: FAIL because the template lacks the Skills tab, script, subtitle, and dispatch branch.

- [ ] **Step 3: Inline and dispatch the new view explicitly**

Pass the view source from `renderer.py`:

```python
skills_js=_read_static("views/skills.js"),
```

Inline it after `agents_js` in `dashboard.html`:

```html
<script>{{ skills_js | safe }}</script>
```

Add the sixth accessible tab:

```html
<button data-view="skills" role="tab" aria-selected="false" tabindex="-1">
  Skills
</button>
```

Add the subtitle and dispatch without changing the terminal unknown-view guard:

```javascript
skills:
  "Whole-corpus skill invocation and adoption reporting — scoped by the dashboard CLI window.",
```

```javascript
} else if (view === 'skills') {
  renderSkills(_container);
} else if (view === 'advanced') {
  renderEconomics(_container);
} else {
  console.error('Unknown view:', view);
}
```

This ordering extends the explicit dispatch introduced by PR #299 (`src/claude_prospector/templates/dashboard.html:L357-L379`; PR #299).

- [ ] **Step 4: Correct the Breakdown card and wire its pointer**

Remove the unused `skill` member:

```javascript
const state = { period: '7d', tab: 'burn' };
```

Change the existing meta label from “installed” to “invoked” and add:

```html
<button type="button" class="skill-report-link">Open full Skills report</button>
```

Wire the button alongside the existing period and diagnostic-tab listeners:

```javascript
const skillReportLink = root.querySelector('.skill-report-link');
if (skillReportLink) {
  skillReportLink.addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent(
      'economy:switch-view',
      { detail: { view: 'skills' } },
    ));
  });
}
```

The shell already converts this event into `setView(e.detail.view)` (`src/claude_prospector/templates/dashboard.html:L413-L417`).

- [ ] **Step 5: Run integration and syntax checks**

Run:

```bash
uv run pytest -q tests/test_skills_view.py tests/test_agent_search_view.py tests/test_phase2_shell.py tests/test_phase3_views.py
node --check src/claude_prospector/static/views/layout-b-diag.js
node --check src/claude_prospector/static/views/skills.js
```

Expected: all tests and syntax checks pass.

- [ ] **Step 6: Commit the shell integration**

```bash
git add src/claude_prospector/renderer.py src/claude_prospector/templates/dashboard.html src/claude_prospector/static/views/layout-b-diag.js tests/test_skills_view.py tests/test_agent_search_view.py tests/test_phase2_shell.py tests/test_phase3_views.py
git commit -m "feat: wire skill usage dashboard tab"
```

---

### Task 4: Document, package, and verify the complete feature

**Files:**
- Modify: `README.md:63-75`
- Modify: `CHANGELOG.md:8-18`
- Verify: `pyproject.toml:21-26`
- Verify: `docs/superpowers/specs/skill-usage-report.md`

**Interfaces:**
- Produces: user-facing feature documentation and a wheel containing `static/views/skills.js`.
- Consumes: the completed Tasks 1-3 implementation and the existing `static/**/*` package-data rule (`docs/superpowers/specs/skill-usage-report.md:L304-L311`; `pyproject.toml:L21-L26`).

- [ ] **Step 1: Update README and changelog copy**

Replace the README's invoked-only bullet with:

```markdown
- **Skill usage and adoption** — searchable union of invoked and agent-passed
  skills, adoption-gap highlighting, and per-target-agent disclosures
```

Add this Unreleased entry, citing issue #296 without inventing a PR number:

```markdown
- **Skill Usage dashboard report** (issue #296). A dedicated searchable tab
  combines transcript invocation totals with skill-tracker adoption data,
  highlights passed-but-never-invoked skills, and exposes labeled per-target-agent
  disclosures while preserving unknown-versus-zero distinctions.
```

After the PR is created, amend this entry with the actual returned PR number; never commit a `PR #N` placeholder (`docs/superpowers/specs/skill-usage-report.md:L465-L473`; user Pull Requests instructions).

- [ ] **Step 2: Run the complete automated verification suite**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
node --check src/claude_prospector/static/cp-utils.js
node --check src/claude_prospector/static/views/agents.js
node --check src/claude_prospector/static/views/mcp-usage.js
node --check src/claude_prospector/static/views/skills.js
node --check src/claude_prospector/static/views/layout-b-diag.js
uv build --wheel
unzip -l dist/claude_prospector-*.whl | grep 'static/views/skills.js'
```

Expected: 0 test failures, both Ruff commands exit 0, every JavaScript file parses, the wheel builds, and the wheel listing contains `claude_prospector/static/views/skills.js` (`CLAUDE.md:L38-L55`).

- [ ] **Step 3: Perform the required visual checks**

Generate a dashboard from the measured local dataset and inspect desktop and 375px-wide layouts. Verify:

- the six-tab strip scrolls within the viewport;
- typing in the Skills filter retains focus;
- all 52 adoption-tracked skills can be found;
- the 27 passed-never-invoked skills appear in the gap callout;
- target-agent `<details>` disclosures expand without stretching unrelated rows; and
- both empty-state copies remain readable.

The measured counts are recorded in issue #296 comment `5559442726`; the narrow-width and manual-render checks are required by `docs/superpowers/specs/skill-usage-report.md:L474-L510`.

- [ ] **Step 4: Commit documentation and verification-facing changes**

```bash
git add README.md CHANGELOG.md docs/superpowers/specs/skill-usage-report.md
git commit -m "docs: document skill usage report"
```

- [ ] **Step 5: Audit referenced artifacts before PR creation**

Run:

```bash
git diff main...HEAD --stat
git ls-tree HEAD -- docs/superpowers/specs/skill-usage-report.md
git ls-tree HEAD -- docs/superpowers/plans/2026-09-06-skill-usage-report.md
git ls-tree HEAD -- src/claude_prospector/static/views/skills.js
```

Expected: the diff contains every deliverable named by the PR, and all three referenced paths resolve in `HEAD` (user Verify Artifact Persistence instructions).

---

## Final PR Handoff

Before the first push, confirm no PR already exists for `feature-296-skill-usage-report`. Push the branch, create a PR whose body contains `Closes #296` and ends with the required Codex attribution, then add the returned PR number to the changelog and push that follow-up only after verifying the PR remains open (user Pull Requests and GitHub Comments instructions).

The implementation plan remains in the branch while #296 is open. After the implementing PR merges and closes #296, extract any durable rationale not already present in the issue/PR, redirect committed path references, and delete this plan file (user Document Files lifecycle instructions).
