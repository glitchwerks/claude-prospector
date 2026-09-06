---
title: Dashboard agent-stats search/lookup (beyond the three hardcoded Top-N lists)
touches:
  - src/claude_prospector/aggregator.py
  - src/claude_prospector/static/cp-utils.js
  - src/claude_prospector/static/views/agents.js
  - src/claude_prospector/static/views/economics.js
  - src/claude_prospector/static/views/mcp-usage.js
  - src/claude_prospector/templates/dashboard.html
  - src/claude_prospector/renderer.py
  - tests/test_agent_search_view.py
  - tests/test_aggregator.py
  - tests/fixtures/dashboard_snapshot_pre_refactor.json
  - tests/test_phase2_shell.py
  - tests/test_phase3_views.py
  - README.md
  - CHANGELOG.md
skills_relevant:
  - python
---

# Dashboard agent-stats search/lookup — scoping spec (issue #295)

**Status: APPROVED — D-1 resolved 2026-09-02; D-2–D-5 resolved 2026-09-05
in issue #295.** D-1 is settled: a new
top-level **Agents** tab (option (b)), additive to the three existing Top-N
views. The BLOCKING findings from project-reviewer's combined review of this
spec and its sibling (issue #296) are folded in below as required changes, not
open questions — see §5. The original recommendations for D-2–D-5 remain below
as decision history; the confirmed choices are recorded in §6 and #295.

Tracking: issue **#295** (open, created 2026-09-02, milestone **#8** "Dashboard:
agent search + skill usage report" — verified 2026-09-02 via
`api.github.com/repos/glitchwerks/claude-prospector/issues/295`, body reproduced
raw). Sibling: issue **#296** (Skill Usage Report) — see §5 *Shared-shell
collision*, the two features contend for the same six collision sites (five
shell-wiring sites plus a sixth, semantic, coordination site in
`cp-utils.js`).

Baseline file:line citations were read at commit `835534f` on 2026-09-02.
Implementation citations for the exact-period payload were refreshed on the
feature branch on 2026-09-05.

---

## 1. What this is, and what it is not

**It adds a presentation surface plus exact per-session agent summaries.**
`AggregateResult.by_agent` (`aggregator.py:55`, populated
`aggregator.py:207-211`) already holds every observed agent path-key with no
truncation, and `renderer.py:92` already ships it into `window.DATA`. The bounded
periods selected in D-4 require exact message, cache, and model totals per agent,
so session summaries now add `agent_stats` while retaining `agent_tokens` for
compatibility (`aggregator.py:139-181`; #295). There is no raw-data collection or
CLI-command change.

**Additive `--format json` schema change.** `cli/dashboard.py:271` already emits
the complete `by_agent` map in JSON mode. Exact bounded-period metrics add an
`agent_stats` object to each session summary while retaining the existing
`agent_tokens` field (`aggregator.py:139-181`; #295). The command and existing
fields are unchanged.

**Non-goal — deleting the curated Top-N lists.** Issue #295's ask is *"no way to
look up an arbitrary agent's stats"* — an additive lookup capability. The three
existing rankings are curated editorial summaries with distinct meanings (§3);
removing them is out of scope (confirmed by D-1=(b), §6 — the three views stay
untouched).

**Non-goal — escaping fixes to existing views.** `economics.js:804-805`
interpolates transcript-derived agent names into `innerHTML` unescaped
(`${leaf}`). That is a real pre-existing gap (§4), but fixing the *existing*
views is a separate issue. This spec only binds **new** code to escape.

---

## 2. Verified ground truth (the three Top-N sites)

| Tab | File:line | Slice | Source data | Period semantics |
|---|---|---|---|---|
| Overview | `static/views/economics-basic.js:341-343` | `.slice(0, 6)` | `session.agent_tokens` summed over sessions | **hardcoded last 7 days** |
| Breakdown | `static/views/layout-b-diag.js:809` | `.slice(0, 7)` | `computeMovers()` → `CP.reAggregate` over `agent_tokens` (`layout-b-diag.js:490-512`) | **7d vs prior 7d**, sorted by \|Δ%\|, not by tokens |
| Advanced | `static/views/economics.js:828-829` | `.slice(0, 8)` | `window.DATA.by_agent` directly (`economics.js:809`) | **whole-corpus totals**; `ctx.agentPeriods` supplies only the per-message deltas |

Three facts that constrain the design:

1. **The key space is uniform.** `by_agent` keys are
   `AGENT_PATH_SEPARATOR.join(msg.agent_path)` (`aggregator.py:27-43`), separator
   `→` U+2192 (`constants.py:9-12`). `session.agent_tokens` uses the *same*
   `_path_key(m)` (`aggregator.py:151-154`), and `CP.reAggregate` keys off
   `s.agent_stats` with an `agent_tokens` compatibility fallback
   (`cp-utils.js:142-170`). So all three views and `by_agent`
   share one key space. A single match predicate works everywhere.
2. **The period semantics are not uniform** (table above). This is the fact that
   makes D-1 non-symmetric — see §3.
3. **All three views drop `'general'`** (`economics-basic.js:327,336`;
   `layout-b-diag.js:506`; `economics.js:812`). Any surface claiming completeness
   must decide what to do with it (D-4).

**Prior art (citation correction).** The reusable filter pattern is
`static/views/mcp-usage.js`, shipped by **PR #292 for issue #282** — the source
comment says "Issue #282" (`mcp-usage.js:68`) and the test file's docstring says
issue #282 (`tests/test_mcp_usage_view_name_filter.py:1`). Issue #295's own body
mis-cites this as "issue #292" (the PR number). Use **#282 (issue) / #292 (PR)**
in code comments and the changelog. Same shape elsewhere: #279→PR #289,
#281→PR #290, #283→PR #293.

The pattern to copy, verbatim from `mcp-usage.js:587-614`:

- `matchesNameFilter(name, query)` — standalone predicate, case-insensitive
  substring, query pre-normalized by the caller (`mcp-usage.js:75-78`).
- `<input id="mcp-name-filter" type="text" placeholder=... aria-label=... />`
  rendered inside the page head (`mcp-usage.js:599-601`).
- A **separate inner wrapper** `<div id="mcp-server-list">`
  (`mcp-usage.js:606`) whose `.innerHTML` alone is replaced by the `input`
  listener (`mcp-usage.js:609-614`). Replacing `root.innerHTML` would tear down
  and recreate the input, dropping focus and cursor position mid-keystroke. This
  is the load-bearing detail.

---

## 3. Why the two options in issue #295 are not symmetric

Issue #295 asks: *"One shared 'Agents' search component/tab vs. three separate
per-view filter boxes?"*

Because the three views mean three different things (§2 table), **no single
shared component can preserve all three semantics.** The options are therefore:

- **(a) Three per-view filter boxes.** Each view keeps its own period semantics
  and its own Top-N ordering; the box just widens what that view can show. Zero
  behaviour change, three small independent edits. But: three inputs to build and
  test, and none of them is a "look up any agent" surface — you still have to
  know which tab holds the number you want.
- **(b) One shared Agents lookup surface, additive.** Must pick **one** semantic.
  Whole-corpus `by_agent` is the only complete, untruncated, already-authoritative
  one. The three curated Top-N lists stay exactly as they are. Answers #295's
  literal ask ("look up an arbitrary agent's stats") with one place to look.
- **(c) One shared lookup surface embedded in an existing tab** (Advanced is the
  natural host — it already reads `by_agent` directly). Avoids the tab-bar
  collision with #296 (§5) but buries the feature, which is the exact complaint
  #296 raises about the Skills card.

This is now resolved: D-1=(b) below — a new top-level Agents tab, additive.

---

## 4. Requirements

Numbered so the reviewer and implementer can reference them. R-1..R-6 hold under
every D-1 outcome; R-7..R-9 apply because D-1 resolved to the shared-surface
option (b) — no longer conditional.

**R-1 — One predicate, one definition.** A standalone
`function matchesAgentFilter(name, query)` performing a case-insensitive
substring match, mirroring `matchesNameFilter` (`mcp-usage.js:75-78`) and the
dedicated-helper convention established by `isGuidLike`/`isDormantServer`. Not
inline comparisons duplicated per call site.

**R-2 — Full-path matching subsumes leaf matching.** The predicate matches
against the **full path key** (`code-writer` is a substring of
`general→code-writer`, so a leaf-name query still hits). Consequence to state in
the UI copy: querying a parent name surfaces every descendant path, which is
usually what the user wants but is not obvious. See D-2.

**R-3 — Focus preservation.** The `input` listener must re-render a **scoped
inner wrapper**, never `root.innerHTML`. This is the one behaviour the test file
must pin hardest, because it is invisible in a screenshot and only shows up while
typing.

**R-4 — Escape at the sink.** Any new code interpolating an agent name into
`innerHTML` must escape it first. `renderer.py:109-113` escapes only `&`, `<`,
`>` — and only to stop a `</script>` breakout from the embedded JSON; `JSON.parse`
decodes those back, so `window.DATA` strings arrive at innerHTML sinks live. That
is precisely why `mcp-usage.js:17-24` escapes a second time. Copy that `esc()`
helper (or promote it to `CP.esc` — see R-6).

**R-5 — Empty-result state.** A query matching nothing must render an explicit
"no agents match" message, not a blank region (cf.
`mcp-usage.js:350-352`).

**R-6 — Promote shared helpers to `cp-utils.js`, don't triplicate.**
`economics.js:800-806` already has `agentLeaf(name)` splitting on `'→'` to render
`leaf` + parent chain. If more than one view needs it, promote it to `CP.agentLeaf`
(escaping its output per R-4) rather than copy-pasting. Same for `esc()` if two
views need it. Note the separator is currently hardcoded as a JS string literal
`'→'` in `economics.js:801`, duplicating `constants.py:12` — a shared
`CP.AGENT_PATH_SEP` is the cheapest place to stop that drifting. **This spec's
own R-1 predicate is not itself promoted here** (`matchesAgentFilter` stays a
local copy, mirroring `matchesNameFilter` in `mcp-usage.js:75-78`) — that's a
deliberate scope cut, not an oversight; see the Phase 1 action item in §7 for
the follow-up.

**R-7 (applies — D-1=(b), D-4=(b)) — Period-aware, with an exact all-time
path.** The lookup surface defaults to `7d` and exposes `5h`, `24h`, `7d`,
`30d`, and `all`. Bounded periods filter `window.DATA.sessions` through
`CP.filterSessions` and rebuild agent totals through `CP.reAggregate` from the
exact per-session `agent_stats` payload (`aggregator.py:139-181`,
`static/cp-utils.js:142-216`); `all` reads the authoritative
`window.DATA.by_agent` payload directly (`aggregator.py:207-211`). State the
selected-period basis in the panel copy. User decision: #295.

**R-8 (applies — D-1=(b)) — Columns.** Show, per matched agent path: leaf + parent
chain, `primary_model` (badge), `total_tokens`, `message_count`,
`session_count`, and the cache split (`cache_creation_tokens` /
`cache_read_tokens`) — every field `aggregator.py:64-75,207-223` actually
populates. No derived metrics that duplicate the Advanced tab's per-message
economics.

**R-9 (applies — D-1=(b)) — Tab-shell wiring.** See §5. The `_renderView`
fallthrough is a live footgun; stacking a new branch ahead of the existing
terminal `else` does **not** close it on its own — the required fix is in §5.

**R-10 — Test file follows the source-containment convention.** New file
`tests/test_agent_search_view.py`, modelled on
`tests/test_mcp_usage_view_name_filter.py` (which is the reference implementation
of this convention — see its docstring at lines 11-37). It must pin, at minimum:
the input element id + purpose-hinting placeholder/aria-label; a two-parameter
predicate declaration with `.toLowerCase()` and `.includes(`; an
`addEventListener('input', ...)` wired near that id and reading `.value`; and —
the R-3 assertion the MCP tests do *not* have — that the listener's re-render
target is an id **other than** the view root, proving the scoped-swap.
Additionally (now unconditional — D-1=(b)): a `data-view="agents"` assertion in
rendered HTML (mirroring `tests/test_mcp_usage_view.py:226-233`); an
entry-function-name assertion (mirroring `tests/test_phase3_views.py:224-231`);
assertions for all five approved period values and the
`CP.filterSessions`/`CP.reAggregate` path;
assertions that an explicit `else if (view === 'advanced')` branch and explicit
no-match handling exist (§5's BLOCKING fix); and a `_VIEW_SUBS` `agents:`
key-presence assertion in rendered HTML (§5, §7 Phase 3).

---

## 5. Shared-shell collision with issue #296

Both #295 (confirmed D-1=(b), a new top-level Agents tab) and #296 (confirmed
D-1=(a) in its own spec, a new top-level Skills tab) touch the same six
collision sites. Five are textual — same lines in `renderer.py` /
`dashboard.html` — and conflict on git merge if landed out of order; the sixth
is semantic, a shared JS namespace, and does **not** show up as a merge
conflict, which is exactly what makes it easy to miss (*Site 6* below).
**Sequencing (required):** per §6 D-5 and §7, this spec's PR lands first;
#296's spec explicitly depends on that landing.

1. `renderer.py:122-125` — the `_read_static("views/*.js")` kwargs list.
2. `templates/dashboard.html:293-297` — the `<script>{{ ..._js | safe }}</script>`
   inline block.
3. `templates/dashboard.html:307-321` — the `.view-toggle` `<button data-view=>`
   block.
4. `templates/dashboard.html:334-345` — the `_VIEW_SUBS` subtitle map.
5. `templates/dashboard.html:347-366` — the `_renderView` if/else chain.
6. `static/cp-utils.js` — the shared `window.CP` namespace
   (`window.CP = {` at `cp-utils.js:319`). Not a line-range collision like
   1-5; a **coordination** collision. This spec's Phase 1 (§7) promotes
   `CP.esc`, `CP.agentLeaf`, and `CP.AGENT_PATH_SEP` — none of which exist in
   `CP` today (`esc` is a local helper at `mcp-usage.js:22`; `agentLeaf` is
   local to `economics.js:800`). Because #296 lands second, its spec must
   consume these promoted exports rather than recreating them — its own R-3
   is written to do that conditionally. If the two PRs are ever bundled into
   one (D-5=(b)), site 6 collapses back into an ordinary same-PR coordination
   concern rather than a cross-PR one.

**Fix required at site 5 (BLOCKING — project-reviewer, 2026-09-02).** Stacking
a new `else if (view === 'agents')` branch ahead of the existing terminal
`else` does **not** close the footgun, because that `else` is *simultaneously*
the dispatch path for the legitimate `advanced` tab **and** the silent
catch-all for typos or unknown view names (`dashboard.html:362-363`,
`renderEconomics(_container)`). An exhaustiveness test cannot be written
cleanly while `advanced` shares the catch-all with "unrecognized." Because
this spec's PR lands first (above), it must:

- Add an explicit `else if (view === 'advanced') { renderEconomics(_container); }`
  branch, alongside the new `else if (view === 'agents')` branch.
- Change the terminal `else` to explicit no-match handling — e.g.
  `console.error('Unknown view:', view)` — instead of silently rendering the
  Advanced tab.

This matters beyond keyboard/mouse clicks: the `economy:switch-view` custom
event listener (`dashboard.html:382-385`) calls `setView(e.detail.view)` with
an arbitrary string from `e.detail.view`, not just a button-sourced value —
another path that can reach an unrecognized `view` and should warn rather than
silently render Advanced. Once the terminal `else` is explicit no-match
handling, the exhaustiveness test R-9/R-10 and this spec's Phase 3 gate want
becomes a simple assertion: every `data-view="X"` button (`basic`, `detail`,
`advanced`, `mcp`, `agents`) has a matching `view === 'X'` branch, no
exemptions.

`tests/test_phase2_shell.py:227-232` asserts only that `data-view="basic"` is
present — there is no tab-count or exhaustiveness assertion anywhere in
`tests/` today, so nothing currently catches a mismatched branch. Phase 3 (§7)
adds that assertion.

**Wheel packaging.** A new `static/views/agents.js` is covered by
`pyproject.toml:24-25` (`static/**/*`), so no manifest edit is needed — but it is
still a **wheel-content change**, which per `CLAUDE.md § CI gates` requires local
verification before PR:

```bash
uv build --wheel
unzip -l dist/claude_prospector-*.whl | grep views
```

---

## 6. Decisions

**D-1 is RESOLVED (2026-09-02, user confirmed). D-2 through D-5 are RESOLVED
(2026-09-05, user confirmed in #295).**

**`touches:` narrowed for D-1=(b).** `economics-basic.js` and
`layout-b-diag.js` (the (a)-only per-view-filter-box files) have been dropped
from the frontmatter; `economics.js` stays — Phase 1 (§7) strips its local
`agentLeaf`/`esc`/`'→'` copies once they're promoted to `cp-utils.js`.
`renderer.py`, `dashboard.html`, and the new `static/views/agents.js` are all
in scope, per D-1=(b).

D-2 through D-5 use the choices recorded below. The required #295 → #296
ordering from §5 remains unchanged.

### D-1 — Shared lookup surface, or three per-view filter boxes? — **RESOLVED: (b)**

**User confirmed 2026-09-02: option (b).** A new top-level **Agents** tab,
additive to the three existing Top-N views (Overview, Breakdown, Advanced),
which stay exactly as they are. D-4 later settled its time basis as
period-aware with an exact all-time path.

- (a) Three per-view filter boxes, each preserving its own period semantics. —
  not chosen.
- (b) One new top-level **Agents** tab, additive — the three Top-N lists
  unchanged. — **chosen.**
- (c) One shared lookup panel embedded inside the existing Advanced tab. — not
  chosen.

This was the recommended option (rationale retained for context): issue
#295's ask reads as a lookup surface, not three narrowing controls; the exact
all-time path can answer "any agent" completely; and the new surface leaves
the three curated views untouched, which keeps
blast radius small despite adding a tab. **Cost:** the §5 collision with #296
(now a required, sequenced fix — see §5), and a fifth tab in the bar (§8
risk).

*Everything downstream of D-1 is now unconditional:* the §5 collision exists
and its fix is required; R-7..R-9 apply; the §7 phasing is the confirmed
direction, not an assumption.

### D-2 — Match the full path chain, or the leaf name only? — **RESOLVED: (a)**

Full-path substring matching (R-2) subsumes leaf matching, so this is really:
**should typing a parent agent's name surface all its descendants?**

- (a) Full-path substring — `general` matches `general→code-writer`,
  `general→debugger`, etc.
- (b) Leaf-segment-only match — `general` matches only the bare `general` key.

**User confirmed 2026-09-05: option (a), recorded in #295.**

*Recommendation: (a),* with the parent-expansion behaviour named in the
placeholder/help copy. It is the more useful default for "where did my tokens go
under this router" and needs no extra code. **Risk:** with `general` as the near-
universal root, a query for a common substring can match nearly everything —
mitigated by result-count display, not by changing the predicate.

### D-3 — Include `'general'` in the lookup surface? — **RESOLVED: (a)**

All three existing views filter it out (§2 fact 3). A surface whose selling point
is completeness arguably should not.

- (a) Include it, labelled (e.g. "root session context").
- (b) Exclude it, matching the three existing views.

**User confirmed 2026-09-05: option (a), recorded in #295.** Label it as
root-session context.

*Recommendation: (a)* for a dedicated lookup surface — now the confirmed shape
per D-1=(b). (The alternative, (b), was scoped for a D-1=(a) outcome that was
not chosen — that branch is moot.) **This is a genuine judgment call about
what `general` represents** — if its token total is misleading rather than
merely large, (b) is right regardless.

### D-4 — Does the lookup surface respect the client-side period selector? — **RESOLVED: (b)**

- (a) No — whole-corpus `by_agent`, with a stated time basis (mirrors MCP Usage,
  `mcp-usage.js:1-5,99-110`).
- (b) Yes — re-aggregate client-side via `CP.reAggregate(CP.filterSessions(...))`
  (`cp-utils.js:101-218`), giving 5h/24h/7d/30d/all like the Breakdown tab.

**User confirmed 2026-09-05: option (b), recorded in #295.** The new tab owns
its period control because the shell has no global selector.

The implemented choice is (b): the new tab owns its period control because the
shell has no global selector, and the exact per-session payload prevents bounded
periods from presenting apportioned message, cache, or model totals (#295).

### D-5 — Ship one PR or two? — **RESOLVED: (a)**

Since D-1=(b) is confirmed, this feature and #296 (also confirmed to add a
tab, D-1=(a) in its own spec) both edit the same six sites (§5) — five
textual, one semantic (`cp-utils.js`'s `CP` namespace).

- (a) Two sequential PRs, second rebased on the first.
- (b) One bundled PR closing both #295 and #296.

**User confirmed 2026-09-05: option (a), recorded in #295.**

*Recommendation: (a),* sequenced #295 → #296, so each issue gets its own review
and its own changelog entry. **Requires** the second implementer to be told the
first has landed. **Note:** the #295 → #296 ordering itself is now required
The chosen two-PR sequence is #295 → #296 because #296's spec depends on the `CP.esc` /
`CP.agentLeaf` / `CP.AGENT_PATH_SEP` exports this spec's Phase 1 adds, and on
the `_renderView` no-match-handling fix this spec's Phase 3 adds (§5).

---

## 7. Phasing (confirmed: D-1=(b), D-2=(a), D-3=(a), D-4=(b), D-5=(a))

**All decisions are settled — this phasing is the confirmed direction.**

**Phase 0 — test-first.** Write `tests/test_agent_search_view.py` per R-10. It
must fail red for the right reason (`FileNotFoundError` on the missing
`views/agents.js`, per the convention noted in
`tests/test_mcp_usage_view_name_filter.py:54-59`).

**Phase 1 — shared helpers.** Promote `esc()`, `agentLeaf()`, and the `'→'`
literal into `cp-utils.js` as `CP.esc` / `CP.agentLeaf` / `CP.AGENT_PATH_SEP`
(R-4, R-6). Leave `economics.js`'s local copies calling through, or delete them —
whichever keeps `economics.js`'s diff smallest. **Action item:** file a
follow-up GitHub issue tracking promotion of the name-filter predicate family
(`matchesNameFilter` in `mcp-usage.js:75-78`, this spec's `matchesAgentFilter`,
and skill-usage-report.md's filter predicate if its D-6 ships one) to a single
`CP.matchesNameFilter` — not done in this PR, but tracked concretely rather
than left as an informal cross-spec note (§5 Site 6). **Gate:** full
`uv run pytest` green with no view behaviour change.

**Phase 2 — the view.** New `static/views/agents.js` exposing
`window.renderAgents(root)`: page head with selected-period subtitle,
`<input id="agent-name-filter">`, and a tab-local `5h`/`24h`/`7d`/`30d`/`all`
control, then `<div id="agent-result-list">` as the scoped swap target (R-3).
Default to `7d`; use the exact authoritative `by_agent` payload for `all` and
the R-7 exact per-session filtered/re-aggregated path for bounded periods.
Render R-8's columns
for every matching agent entry, including labeled root-session context for
`general`.
**Gate:** Phase 0 tests green.

**Phase 3 — shell wiring.** All six §5 sites: add an explicit
`else if (view === 'agents')` branch **and** an explicit
`else if (view === 'advanced') { renderEconomics(_container); }` branch, and
change the terminal `else` to no-match handling (`console.error('Unknown
view:', view)`) instead of silently rendering Advanced — this is the BLOCKING
fix from §5, required in this PR since it lands first. Add the `agents` entry
to `_VIEW_SUBS` (object keys in this literal are unquoted, e.g. `agents:`, not
`"agents":`). **Gate:** `data-view="agents"` and `renderAgents` both present in
rendered HTML; the `agents:` key present in the rendered `_VIEW_SUBS` object
alongside its subtitle text; an exhaustiveness assertion that every
`data-view="X"` button (`basic`, `detail`, `advanced`, `mcp`, `agents`) has a
matching `view === 'X'` branch in `_renderView`, no exemptions; the whole suite
green.

**Phase 4 — docs + packaging.** `README.md` — **verified 2026-09-02**: the
`dashboard` subcommand section (README.md:225-286) is a flag reference and does
**not** enumerate tabs, so it needs no change. The place that does is the
`usage-dashboard` skill's feature bullet list at **README.md:67-74**, whose
"**Agent breakdown** — token usage per agent with model attribution and nested
sub-agent tracing" bullet (README.md:71) is the line to extend. Plus
a `CHANGELOG.md` `### Added` entry under a new Unreleased heading, following the
`0.13.0` entry format (`CHANGELOG.md:12-16`) and citing **issue #295 / PR #N**.
**Gate:** the wheel-content check in §5, plus both lint commands
(`uv run ruff check .` **and** `uv run ruff format --check .` — per
`CLAUDE.md § CI gates`, `check` alone is not the CI gate).

---

## 8. Risks

- **R-3 is untestable by execution.** No JS runs in CI (no `package.json`, no
  jsdom — `tests/test_mcp_usage_view_name_filter.py:11-18`). The focus-preservation
  behaviour can only be pinned structurally ("the swap target id ≠ the root"). A
  reviewer must still open the dashboard and type into the box. Put that on the
  PR's test plan as a completable item.
- **Fifth tab crowding.** The `.view-toggle` bar (`dashboard.html:307-321`) is a
  flex row with no wrap handling of its own beyond `.shell-head { flex-wrap:
  wrap }` (`dashboard.html:29`). Five tabs plus the "Power user" badge may wrap
  awkwardly at narrow widths. Worth a visual check, not a blocker.
- **`unverified:` — dataset size.** Nobody has stated how many distinct agent
  path-keys a typical `by_agent` holds. If it is ~20, a filter box is nearly
  pointless and a plain sortable full list would do; if it is ~500, pagination
  matters. **This is load-bearing for whether the feature is worth building as
  specified.** Cheapest check:

  ```bash
  uv run python -m claude_prospector dashboard --format json \
    | uv run python -c "import json,sys; print(len(json.load(sys.stdin)['by_agent']))"
  ```

  Note: **`uv run`, not bare `python`** — `CLAUDE.md § Python interpreter and
  test commands` records that bare invocations fall through to system Python
  3.14 on this host, where `claude_prospector` is not installed (#136 / PR
  #137). `--format json` writes status text to stderr
  (`cli/dashboard.py:178`) so stdout is a clean pipe, and the json branch
  returns before `render()` (`cli/dashboard.py:264-282`), so `--no-open` is a
  no-op here.

---

## 9. Sibling issues recommended (not filed — out of scope here)

1. `economics.js:804-805` (`agentLeaf`) and `layout-b-diag.js:1069` interpolate
   transcript-derived names into `innerHTML` unescaped. Pre-existing, not
   introduced by #295; R-4 binds only new code.
2. ~~No test anywhere asserts the `_renderView` branch set is exhaustive~~ —
   **addressed by this spec.** §5's BLOCKING fix and §7 Phase 3 now require an
   explicit `advanced` branch, explicit no-match handling, and an
   exhaustiveness test assertion. No longer a sibling-issue candidate.
