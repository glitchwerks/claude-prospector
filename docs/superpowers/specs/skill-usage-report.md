---
title: Dashboard Skill Usage Report (promote skills from a buried card to a real report)
touches:
  - src/claude_prospector/static/views/skills.js
  - src/claude_prospector/static/views/layout-b-diag.js
  - src/claude_prospector/static/cp-utils.js
  - src/claude_prospector/templates/dashboard.html
  - src/claude_prospector/renderer.py
  - tests/test_skills_view.py
  - tests/test_phase2_shell.py
  - tests/test_phase3_views.py
  - README.md
  - CHANGELOG.md
skills_relevant:
  - python
---

# Dashboard Skill Usage Report — scoping spec (issue #296)

**Status: DRAFT — D-1 resolved 2026-09-02; 6 open decisions (§6: D-2–D-7) still
pending user resolution. Not ready to implement.** D-1 is settled: a new
top-level **Skills** tab (option (a)), promoting skill-usage reporting out of
the buried Breakdown-tab card. The BLOCKING findings from project-reviewer's
combined review of this spec and its sibling (issue #295) are folded in below
as required changes, not open questions — see §5. This spec also depends on
#295 landing first for its CP-namespace API surface — see §5 *sequencing*.
Remaining recommended answers (D-2–D-7) are marked *Recommendation* and are
explicitly **not** settled. Resolve those next; §7's phasing is written
against the recommendations and must be re-derived if one lands elsewhere.

Tracking: issue **#296** (open, created 2026-09-02, milestone **#8** — verified
2026-09-02 via `api.github.com/repos/glitchwerks/claude-prospector/issues/296`,
body reproduced raw). Sibling: issue **#295** (agent search) — see §5, both
features contend for the same six collision sites (five shell-wiring sites
plus a sixth, semantic, coordination site in `cp-utils.js`).

All file:line citations below were read at commit `835534f` on 2026-09-02.

---

## 1. What this is, and what it is not

**It is a presentation-layer change only.** Both data sources already reach
`window.DATA` (`renderer.py:93-94`). There is no collection gap.

**Non-goal — `--format json`.** `cli/dashboard.py:272,277` already emits both
`by_skill` and `by_skill_adoption`. This feature adds nothing to that payload.

**Non-goal — the `audit` subcommand's "skill" concept.** `cli/audit.py`'s static
installed-skill-file inventory (collision detection) is a different thing
entirely. Do not join, merge, or reconcile it with usage data here.

**Non-goal — new aggregation.** D-5 discusses one thing the data *cannot*
currently do (period slicing); the answer is to state the limitation, not to add
a per-session skill field.

---

## 2. Verified ground truth — and the finding that reframes the issue

### 2.1 There are three different "skill populations", not one

| Population | Source | What it means |
|---|---|---|
| `by_skill` | `aggregator.py:206-212` — an entry is created only when `msg.skill is not None`, from `parser.py:_extract_skill` | Skills **invoked at least once** in the window |
| `by_skill_adoption` | `aggregator.py:272-295`; docstring at `aggregator.py:251-254`: *"Only skills with at least one skill_passed event appear"* | Skills **passed to an agent** — **including ones never invoked** (`times_invoked: 0`, `adoption_rate: 0.0`) |
| "installed" | `cli/audit.py` static inventory | Out of scope (§1) |

**These two sets are neither equal nor nested.** A skill invoked directly by the
user, with no dispatch-time pass, is in `by_skill` but not `by_skill_adoption`. A
skill passed in a brief and ignored is in `by_skill_adoption` but **not** in
`by_skill`.

### 2.2 The actual bug in the existing card

`layout-b-diag.js:1036-1044` iterates `Object.entries(window.DATA.by_skill)` and
looks up `adoptAll[name]` — a **left join keyed on the invoked set**. Therefore:

> **A skill that was passed but never invoked — adoption_rate 0, which is the
> single most actionable signal an adoption report can carry — is invisible in
> the current card.**

This reframes #296. The ask is not merely "the card is small and buried"; the
card **structurally cannot show the finding the data exists to show**. The new
report must iterate the **union** of `Object.keys(by_skill)` and
`Object.keys(by_skill_adoption)` (R-1). That is a pinnable test assertion.

### 2.3 A second, smaller mislabel

`layout-b-diag.js:1056` renders `${allSkills.length} installed` — but
`allSkills` is built from `by_skill`, i.e. **skills invoked in the window**, not
skills installed. The new report must not inherit that framing; whether the
existing card's label gets fixed depends on D-2.

### 2.4 `by_target_agent` is **not joinable** to `by_agent`

- `by_target_agent` keys come from `evt.target_agent`
  (`aggregator.py:284-286`), which is `entry["target_agent"]` read straight out
  of the skill-tracker hook's JSONL (`skill_tracking.py:82`). Test fixtures
  throughout show bare agent-type names: `"code-writer"`, `"debugger"`
  (`tests/test_aggregator_adoption.py:29`, `tests/test_skill_tracking.py:47,84`).
- `by_agent` keys are `→`-joined **full path chains**
  (`aggregator.py:27-43`, separator `constants.py:12`).

A leaf-name join between them is a lossy many-to-one fan-in (`code-writer`
collapses `general→code-writer`, `general→X→code-writer`, …) and would silently
misattribute. **Do not cross-link the two.** D-3 covers how to surface
`by_target_agent` honestly instead.

### 2.5 The report cannot be period-aware

Session summaries (`aggregator.py:151-174`) carry **no skill field** — the keys
are `session_id, project, project_path, start_time, root_agent, agents,
agent_tokens, total_tokens, input_tokens, output_tokens, cache_creation_tokens,
cache_read_tokens, model_split, duration_minutes, message_count`. So
`CP.filterSessions` + `CP.reAggregate` (`cp-utils.js:100-139`), which is how
every period-aware view works, has nothing to re-slice skills by.

Skill data's only time bounds are the CLI's `--from`/`--to`/`--window`, applied
once server-side (`cli/dashboard.py:189-216`). This is the **same posture as MCP
Usage** (D-H=(b), `mcp-usage.js:1-5`), which states its basis in copy via
`timeBasisLine()` (`mcp-usage.js:99-110`) and in the shell subtitle
(`dashboard.html:342-344`). Reuse that posture (R-5).

### 2.6 The dead stub is real

`layout-b-diag.js:986` declares
`const state = { period: '7d', tab: 'burn', skill: { q: '', sort: 'use' } }`.
`state.period` and `state.tab` are read throughout (`layout-b-diag.js:990,1006,
1016,1023`); `state.skill` is read **nowhere**. It is dead. D-4 decides its fate.

### 2.7 Prior art (citation correction)

The filter/search pattern to copy is `mcp-usage.js`, from **issue #282 / PR #292**
(`mcp-usage.js:68`; `tests/test_mcp_usage_view_name_filter.py:1`). The
tab-promotion precedent #296 cites — MCP Usage going from buried element to
top-level tab — is **issue #248**, PRs #259–#261 (recorded in
`docs/superpowers/specs/mcp-tool-usage-analyzer.md:26-34`); `CHANGELOG.md:48`
confirms *"New 'MCP Usage' tab in the … (issue #248)"*. The
many-rows-collapse-into-`<details>` pattern is **issue #283 / PR #293**
(`CHANGELOG.md:17-21`) — directly relevant to D-3.

---

## 3. Requirements

**R-1 — Union population.** Iterate the union of `Object.keys(by_skill)` and
`Object.keys(by_skill_adoption)`. Each row must distinguish four states
explicitly, never collapsing them into a zero:

| State | `by_skill` | `by_skill_adoption` | Display |
|---|---|---|---|
| passed and invoked | present | present | invocations + adoption % |
| **passed, not invoked in-window** | absent | present | invocations 0, adoption = the **actual** `adoption_rate` |
| invoked without a recorded pass | present | absent | invocations N, times passed **"—"**, times invoked **"—"** (not `0` — not tracked, not confirmed zero), adoption **"—" / n/a** (not 0%) |
| neither | — | — | not rendered |

**Row 2: render `adoption_rate` as it actually is; do not hardcode 0%.** The two
sources are filtered independently — `by_skill` on transcript **message**
timestamps (`aggregator.py:206-212` over `filtered_messages`),
`by_skill_adoption` on hook **event** timestamps (`aggregator.py:256-261`) — so
at a window edge they can disagree, and "absent from `by_skill`" does not
strictly imply `times_invoked == 0`. Accordingly the **highlight** in R-1's
adoption-gap callout must trigger on `adoption_rate == 0`, not on `by_skill`
absence.

Row 2 is the finding §2.2 says is currently invisible. Row 3's "—" vs "0%"
distinction mirrors `mcp-usage.js:26-38`'s deliberate `null`-vs-`0` handling
(`formatCountOrUnknown`) — collapsing "not observable" into "observed as zero" is
the exact mistake that file documents avoiding.

**Footnote (project-reviewer, 2026-09-02) — "invocations" and "times invoked"
are not the same count, and can diverge at window edges.** "Invocations" (the
main-table column, §4 item 3) is sourced from `by_skill[*].invocation_count` —
a count of transcript *messages* where `msg.skill` matched, incremented per
message (`aggregator.py:206-212`). "Times invoked" is sourced from
`by_skill_adoption[*].times_invoked` — a count of `skill_passed` events whose
session also had a correlated `skill_invoked` event, computed by intersecting
two independently-filtered event streams (`aggregator.py:256-261,272-277`).
These are different counting methods, over different underlying data (message
timestamps vs. hook-event timestamps), with independently-applied time
windows — they can legitimately disagree in either direction. The rendered
table must carry a footnote explaining this wherever both columns appear side
by side, so a mismatch reads as "these measure different things," not as a
bug.

**R-2 — No mislabelling of the population.** Do not call any count "installed"
(§2.3). Label what it is: "invoked", "passed", "skills seen".

**R-3 — Escape at the sink.** Skill names are transcript- and hook-derived.
`renderer.py:109-113` escapes only `& < >` and only against `</script>` breakout;
`JSON.parse` decodes them back before they reach innerHTML — which is why
`mcp-usage.js:17-24` escapes a second time. New code must escape. (The existing
card at `layout-b-diag.js:1069` does not — pre-existing, see §9.)

**Conditional on #295's landing (BLOCKING — project-reviewer, 2026-09-02).**
agent-stats-search.md (issue #295, confirmed D-1=(b)) promotes a shared
`CP.esc` export to `cp-utils.js` in its own Phase 1. Per §5's sequencing,
#295 lands first. Therefore: **if `CP.esc` is already exported when this
feature is implemented, use it directly; otherwise copy `esc()` from
`mcp-usage.js:17-24` and file a follow-up issue to migrate this copy to
`CP.esc` once #295 lands.** Do not copy-paste `esc()` unconditionally —
doing so after #295 has already promoted it would recreate exactly the
code-triplication agent-stats-search.md's own R-6 says to avoid.

**R-4 — Empty and partial-empty states are different.**
`by_skill_adoption` is `{}` whenever the skill-tracker hook log yields no events
(`cli/dashboard.py:207-216` only assigns it `if passed_events or invoked_events`)
— while `by_skill` may still be fully populated from transcripts. That is
**"invocations recorded, no adoption tracking available"**, and the copy must say
so and point at the hook (`README.md:116` documents `skill-tracker.py`,
PreToolUse). It is *not* the same as the fully-empty state
(cf. `mcp-usage.js:580`'s `renderEmptyState()`), which needs its own message.

**R-5 — State the time basis.** Per §2.5, the report is whole-corpus within the
CLI window and cannot respond to any client-side period selector. Say so in the
panel subtitle, mirroring `mcp-usage.js:102-110` / `dashboard.html:342-344`. Do
**not** ship a period control that silently does nothing.

**R-6 — Search/sort follow the established pattern.** If a filter box ships
(D-6): standalone `matchesNameFilter`-shaped predicate, a scoped inner wrapper
whose `.innerHTML` alone the `input` listener replaces (never `root.innerHTML` —
that drops focus mid-keystroke; `mcp-usage.js:587-614`), and a purpose-hinting
placeholder + `aria-label`. Do not write a third local copy of this predicate:
agent-stats-search.md flags the same duplication (its own `matchesAgentFilter`
vs. `mcp-usage.js`'s `matchesNameFilter`) and recommends a follow-up issue
promoting a single `CP.matchesNameFilter` (§7 Phase 1 of that spec). If that
issue exists by the time D-6 is implemented, use it; otherwise add a local
copy here and note it against that same follow-up issue rather than filing a
fourth one.

**R-7 — Shell wiring (applies — D-1=(a), new tab confirmed).** See §5. The
`_renderView` terminal `else` is `renderEconomics` (`dashboard.html:362-363`)
— a new `data-view` without an explicit branch silently renders Advanced.
#295 (landing first, per §5) closes that ambiguity by making the terminal
`else` explicit no-match handling; this spec's `else if (view === 'skills')`
branch (§7 Phase 3) must land after that fix, not before — see §5.

**R-8 — Test file follows the source-containment convention.** New
`tests/test_skills_view.py`, modelled on
`tests/test_mcp_usage_view_name_filter.py` (docstring at lines 11-37 is the
canonical statement of the convention) and `tests/test_mcp_usage_view.py:226-233`
(asserts `data-view="mcp"` in rendered HTML) plus
`tests/test_phase3_views.py:224-231` (asserts the entry-function name reaches the
HTML). Minimum assertions: the union-iteration marker (that
`by_skill_adoption`'s key set is enumerated, not only indexed by `by_skill`'s
keys); a distinct render path for the never-invoked case; the `data-view` value
and entry-function name; and, if D-6 ships a filter, the R-6 markers.

---

## 4. What the report should contain (D-1=(a), new tab, confirmed)

1. **Header** — title, `timeBasisLine`-style subtitle (R-5), counts labelled per
   R-2 (e.g. "N skills invoked · M passed to agents").
2. **Adoption-gap callout** — the skills with `times_passed > 0` and
   `adoption_rate == 0`, surfaced first. This is the report's reason to exist
   (§2.2). Gated behind R-4's partial-empty state.
3. **Main table** — one row per union member: name, invocations
   (`by_skill[*].invocation_count`, `aggregator.py:211`), total tokens
   (`by_skill[*].total_tokens`, `aggregator.py:212`), times passed, times
   invoked, adoption rate, per R-1's four states and R-1's footnote on why
   "invocations" and "times invoked" are different counts that can diverge.
4. **Per-skill target-agent breakdown** — see D-3.

---

## 5. Shared-shell collision with issue #295

Both this feature (confirmed D-1=(a), a new top-level Skills tab) and #295
(confirmed D-1=(b) in its own spec, a new top-level Agents tab) touch the
same six collision sites. Five are textual — same lines in `renderer.py` /
`dashboard.html` — and conflict on git merge if landed out of order; the
sixth is semantic, a shared JS namespace, and does **not** show up as a merge
conflict, which is exactly what makes it easy to miss (*Site 6* below).

**Sequencing (required).** #295 lands first. Its spec owns the CP-namespace
promotion (`CP.esc`, `CP.agentLeaf`, `CP.AGENT_PATH_SEP`) and the
`_renderView` no-match-handling fix (below). This spec's R-3 is written
conditionally on that landing.

1. `renderer.py:122-125` — `_read_static("views/*.js")` kwargs.
2. `templates/dashboard.html:293-297` — inline `<script>` block.
3. `templates/dashboard.html:307-321` — `.view-toggle` button block.
4. `templates/dashboard.html:334-345` — `_VIEW_SUBS`.
5. `templates/dashboard.html:347-366` — `_renderView` if/else chain (see R-7).
6. `static/cp-utils.js` — the shared `window.CP` namespace
   (`window.CP = {` at `cp-utils.js:262`). Not a line-range collision like
   1-5; a **coordination** collision. This spec's `touches:` frontmatter
   already lists `cp-utils.js`, but this body otherwise only *reads* `CP`
   (`CP.filterSessions`/`CP.reAggregate`, §2.5) — it does not, on its own,
   state that it will *consume* #295's newly-promoted `CP.esc`. R-3 above
   makes that consumption explicit and conditional on #295's landing.

**Fix at site 5 (owned by #295, referenced here for context).** #295's spec
requires an explicit `else if (view === 'advanced') { renderEconomics(_container); }`
branch alongside its new `else if (view === 'agents')` branch, and requires
the terminal `else` at `dashboard.html:362-363` to become explicit no-match
handling (`console.error('Unknown view:', view)`) rather than silently
rendering Advanced — stacking a bare `else if (view === 'skills')` ahead of
the terminal `else` would not close that footgun on its own (the `else` is
simultaneously the `advanced` dispatch path and the silent unknown-view
catch-all). This spec's Phase 3 (§7) adds `else if (view === 'skills')`
**after** #295's fix has landed, so the terminal `else` is already
unambiguous by the time this branch is added.

**Wheel packaging.** `static/views/skills.js` is covered by
`pyproject.toml:24-25` (`static/**/*`) with no manifest edit — but it is still a
wheel-content change, so `CLAUDE.md § CI gates` requires local verification:

```bash
uv build --wheel
unzip -l dist/claude_prospector-*.whl | grep views
```

---

## 6. Open decisions

**D-1 is RESOLVED (2026-09-02, user confirmed).** D-2 through D-7 remain
**UNRESOLVED, user input required.**

**`touches:` confirmed for D-1=(a).** The new `views/skills.js` plus
`renderer.py` and `dashboard.html` are in scope. `layout-b-diag.js` also
remains in scope: D-2 options (a) (delete the card) and (c) (keep it but fix
the label) both edit it; only D-2=(b) (keep it unchanged) would not — kept in
`touches:` as pre-declared breadth until D-2 resolves.

D-2 and D-4 are now **live** questions — previously scoped as "only
meaningful if D-1=(a)" / "flips to (b) if D-1=(b)"; that D-1=(b) branch is
moot since D-1=(a) is what was chosen. D-3 and D-5 can default to the
recommendations; D-6 depends on §8's dataset-size measurement; D-7 (one PR or
two, with #295) is independent of the fix ordering — see §5's sequencing
note, which holds regardless of how D-7 resolves.

### D-1 — New top-level "Skills" tab, or expand the existing Breakdown card? — **RESOLVED: (a)**

**User confirmed 2026-09-02: option (a).** A new top-level **Skills** tab,
promoting skill-usage reporting out of the buried Breakdown-tab card.

- (a) New top-level **Skills** tab (mirrors the #248/#259-#261 MCP Usage
  promotion). — **chosen.**
- (b) Expand the existing card in place at `layout-b-diag.js:1033-1078`. — not
  chosen.
- (c) New tab **and** keep a reduced card in Breakdown as a pointer. — not
  chosen.

This was the recommended option (rationale retained for context): the
union-population fix (R-1), the adoption-gap callout, and the per-skill
target-agent breakdown do not fit a half-width card in a two-column `.row`
(`layout-b-diag.js:1050-1077`), and the MCP promotion is direct precedent.
**Cost:** the §5 collision with #295 (now a required, sequenced fix — see
§5), and a sixth tab in the bar (§8 risk, compounding with #295's fifth).

*Everything downstream of D-1 is now unconditional:* the §5 collision exists
and its sequencing is required; R-7 applies; §4 and §7 describe the confirmed
direction, not an assumption.

### D-2 — What happens to the existing Breakdown card?

**Now live — D-1=(a) confirmed.**

- (a) Delete it; the Breakdown tab's `_VIEW_SUBS` copy at `dashboard.html:338`
  currently promises *"projects, agents, skills and adoption"* and would need
  updating.
- (b) Keep it unchanged (accepting that it keeps hiding never-invoked skills,
  §2.2, and keeps the "installed" mislabel, §2.3).
- (c) Keep it but fix the label and add a "see full report" affordance.

*Recommendation: (c)* — cheapest correct answer; deleting it changes a tab users
already rely on, keeping it as-is knowingly leaves a wrong label on screen.
**Note:** the §2.3 mislabel fix comes free only under (a) or (c); under (b) it
should be filed separately.

### D-3 — Surface `by_target_agent` per skill, or keep it aggregate-only?

Per §2.4 it is **not** joinable to `by_agent`.

- (a) Surface it as a per-skill nested disclosure, using the #283/PR #293
  `<details>` collapse pattern (`CHANGELOG.md:17-21`) so a skill passed to 20
  agents does not dominate its row. Label it explicitly as *"target agent as
  recorded by the skill-tracker hook"*, with no link to the Agents/`by_agent`
  surface.
- (b) Keep aggregate-only for v1.

*Recommendation: (a) with the labelling constraint.* It is the only place this
data is visible at all, and it answers "which agents ignore this skill" — the
natural follow-up to the adoption-gap callout. **Hard constraint either way: no
join to `by_agent`, no leaf-name matching between the two key spaces.**

### D-4 — Finish the dead `state.skill` stub, or delete it?

- (a) Delete `skill: { q: '', sort: 'use' }` from `layout-b-diag.js:986`.
- (b) Wire it up for an in-card search/sort — **moot: only coherent under
  D-1=(b), which was not chosen.**

*Recommendation: (a).* Under the confirmed D-1=(a), the stub's intended home
moves to the new view entirely, and a new view should own its own state
rather than inherit an abandoned shape. Deleting it is a one-line diff with
zero behaviour change (it is read nowhere — §2.6).

### D-5 — Ship a period control?

*Recommendation: no* — §2.5 makes it impossible without a data-layer change, and
a control that silently does nothing is worse than none. State the time basis in
copy instead (R-5). **Only in play as an alternative:** add a `skills` field to
each session summary in `aggregator.py:151-174`, which is a real aggregator
change and belongs in its own issue, not here.

### D-6 — Ship a name filter in v1?

- (a) Yes — copy the #282/PR #292 pattern (R-6).
- (b) No — the current card is already an untruncated scrollable list
  (`layout-b-diag.js:1063-1075`), so search may be unnecessary at this dataset
  size.

*Recommendation: depends on §8's dataset-size check.* Under ~30 skills a sortable
table needs no search box. **Do not decide this from the armchair — run the count
first.**

### D-7 — Ship one PR or two (with #295)?

- (a) Two sequential PRs, sequenced #295 → #296.
- (b) One bundled PR closing both.

*Recommendation: (a).* Mirrors #295's D-5; keeps per-issue review granularity and
per-issue changelog entries. **Requires** the second implementer to be told the
first has landed, since both edit the same six sites (§5). **Note:** the
#295 → #296 ordering itself is now required regardless of how D-7 resolves —
this spec's R-3 depends on #295's `CP.esc` export and this spec's Phase 3
depends on #295's `_renderView` no-match-handling fix (§5). D-7 only decides
whether that ordering happens as two PRs or as one PR with two
internally-sequenced phases.

---

## 7. Phasing (D-1=(a) confirmed; written against D-2=(c), D-3=(a), D-4=(a), D-5=no, D-7=(a) recommendations)

**D-1 is settled — this phasing is the confirmed direction, not an
assumption. Re-derive Phases 2-5 below only if D-2, D-3, D-4, D-5, or D-7
resolve differently from their recommendations.**

**Phase 0 — dataset reality check.** Run §8's command. Its output resolves D-6
and tells you whether the adoption-gap callout will have any rows at all on this
machine. **Do not skip:** if `by_skill_adoption` is `{}` here, the whole R-1
union finding is unobservable locally and every review of this feature is
blind-flying.

**Phase 1 — test-first.** `tests/test_skills_view.py` per R-8. Red for the right
reason (`FileNotFoundError` on the missing `views/skills.js`).

**Phase 2 — the view.** New `static/views/skills.js` exposing
`window.renderSkills(root)`: header (R-2, R-5), adoption-gap callout, union table
(R-1), per-skill `<details>` target-agent breakdown (D-3a), `esc()` at every sink
(R-3), both empty states (R-4). **Gate:** Phase 1 tests green.

**Phase 3 — shell wiring.** All six §5 sites, with an explicit
`else if (view === 'skills')` branch (R-7) added **after confirming #295 has
already landed its `else if (view === 'advanced')` branch and no-match
handling** — do not add this branch against a pre-#295 `dashboard.html`, or
the terminal-`else` footgun (§5) reopens for this PR too. Add the `skills`
entry to `_VIEW_SUBS` (object keys in this literal are unquoted, e.g.
`skills:`, not `"skills":`). **Gate:** `data-view="skills"` and `renderSkills`
both in rendered HTML; the `skills:` key present in the rendered `_VIEW_SUBS`
object alongside its subtitle text; #295's exhaustiveness assertion still
passes with `skills` added to the checked set; full suite green.

**Phase 4 — Breakdown-card cleanup (D-2c).** Fix the `layout-b-diag.js:1056`
label; add the pointer affordance; delete the `state.skill` stub
(`layout-b-diag.js:986`, D-4a). **Gate:** no behaviour change beyond the label.

**Phase 5 — docs + packaging.** `README.md` — **verified 2026-09-02**: the
`dashboard` subcommand section (README.md:225-286) is a flag reference and does
**not** enumerate tabs, so it needs no change. The line that does need updating is
the `usage-dashboard` skill's feature bullet **"Skill usage — invocation counts
per skill"** (README.md:72), which describes exactly the invoked-only framing this
spec replaces (§2.1). Plus a `CHANGELOG.md` `### Added` entry citing
**issue #296 / PR #N**, following the `0.13.0` format
(`CHANGELOG.md:12-21`). **Gate:** §5's wheel check plus **both** lint commands
(`uv run ruff check .` **and** `uv run ruff format --check .` — per
`CLAUDE.md § CI gates`).

---

## 8. Risks

- **`unverified:` — the report may be empty on the target machine.** Whether
  `by_skill_adoption` has data depends entirely on whether the `skill-tracker`
  PreToolUse hook is installed and has been logging (`README.md:116`;
  `cli/dashboard.py:207`). Check before building:

  ```bash
  uv run python -m claude_prospector dashboard --format json \
    | uv run python -c "import json,sys; d=json.load(sys.stdin); \
      print('by_skill:', len(d['by_skill']), '| adoption:', len(d['by_skill_adoption']), \
      '| passed-never-invoked:', sum(1 for v in d['by_skill_adoption'].values() if v['times_invoked']==0))"
  ```

  Note: **`uv run`, not bare `python`** — `CLAUDE.md § Python interpreter and
  test commands` records that bare invocations fall through to system Python
  3.14 on this host, where `claude_prospector` is not installed (#136 / PR
  #137). `--format json` writes status text to stderr
  (`cli/dashboard.py:178`) so stdout is a clean pipe, and the json branch
  returns before `render()` (`cli/dashboard.py:264-282`), so `--no-open` is a
  no-op here.

  **This is load-bearing.** If the third number is 0, the feature's headline
  callout has nothing to show on this machine, and the cost of the §5
  collision with #295 (already accepted via D-1) is being paid for a report
  that can't demonstrate its own reason to exist locally — worth flagging to
  the reviewer even though D-1 itself is settled.
- **No JS execution in CI.** Source-containment tests cannot prove the union
  iteration actually renders the never-invoked rows — only that the code shape is
  there. A reviewer must open the dashboard and eyeball it; put that on the PR
  test plan as a completable item.
- **Tab crowding.** With #295 this becomes a six-tab bar
  (`dashboard.html:307-321`); worth a narrow-width visual check.

---

## 9. Sibling issues recommended (not filed — out of scope here)

1. `layout-b-diag.js:1069` interpolates transcript-derived skill names into
   `innerHTML` unescaped (`${s.name}`). Same class as `economics.js:804-805` for
   agent names. Pre-existing; R-3 binds only new code. If D-2=(b) this stays
   unfixed, so file it.
2. The "N installed" mislabel (`layout-b-diag.js:1056`) — free under D-2=(a)/(c),
   needs its own issue under D-2=(b).
3. Adding a per-session `skills` field to `aggregator.py:151-174` to make skill
   data period-sliceable client-side (§2.5, D-5's alternative). Real aggregator
   work; own issue.
4. ~~No test asserts the `_renderView` branch set is exhaustive~~ —
   **addressed by #295's PR** (issue #295, landing first per §5): its
   BLOCKING fix adds an explicit `advanced` branch, explicit no-match
   handling, and an exhaustiveness test assertion that this spec's Phase 3
   (§7) extends to cover `skills`. No longer a sibling-issue candidate.
