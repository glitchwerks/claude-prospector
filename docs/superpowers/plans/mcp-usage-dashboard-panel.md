---
title: MCP tool-usage dashboard panel (issue #248, spec Phase 3)
touches:
  - src/claude_prospector/tool_collection.py
  - src/claude_prospector/cli/tool_usage.py
  - src/claude_prospector/cli/dashboard.py
  - src/claude_prospector/aggregator.py
  - src/claude_prospector/renderer.py # `data` dict always; `_read_static` kwarg only under D-D=(a)
  - src/claude_prospector/templates/dashboard.html # only under D-D=(a)
  - src/claude_prospector/static/views/layout-b-diag.js # only under D-D=(b) — ctx line + TAB_DEFS row + build fn
  - src/claude_prospector/static/views/mcp-usage.js # new file, only under D-D=(a) — which D-H=(b) selects
  - tests/unit/test_tool_usage.py
  - tests/test_cli_subcommands.py
  - tests/test_renderer.py
  - tests/test_phase3_views.py
  - tests/test_aggregator_tool_usage.py
  - tests/test_phase2_shell.py # gate only — run unmodified, not edited
  - tests/unit/test_tool_collection.py # gate only under D-J=(a); edited only if the merged pass adds cases
  - hooks/dashboard-regen.py # only under D-I=(b)/(c); see §3 D-I
  - hooks/hooks.json # only under D-I=(b)
  - .claude-plugin/plugin.json # only under D-I=(b) — adds a userConfig key
  - tests/test_dashboard_regen_hook.py # gate under D-I=(a); edited under D-I=(b)/(c)
  - tests/test_dashboard_snapshot.py # only if D-C=(a) stays in scope
  - tests/fixtures/dashboard_snapshot_pre_refactor.json # only if D-C=(a) stays in scope
  - docs/superpowers/specs/mcp-tool-usage-analyzer.md
  - README.md
skills_relevant:
  - python
---

# MCP tool-usage dashboard panel — plan (issue #248)

> **STATUS: SCOPE CONFIRMED.** Issue #248 was originally labelled "not yet
> scoped/planned". §3 below is a table of eleven decisions — **all eleven now
> RESOLVED**: three (D-F, D-G, D-K) by constraints this file already carried,
> and the remaining eight confirmed directly by the user (Rev 4). §5's phases
> were drafted **against the recommendations**, and every confirmation matched
> its row's Recommended column — no phase changes shape.
>
> **Confirm before Phase 0:** D-A, D-J — **confirmed, Rev 4.**
> **Confirm before Phase 1:** D-B, D-C — **confirmed, Rev 4.**
> **Confirm before Phase 2:** D-H, D-D, D-E — **confirmed, Rev 4** (D-H was
> confirmed first, per its own gating note; its answer flips D-D, and D-E's
> copy depends on D-I — see the Rev 4 entry below for the resolved chain).
> **Confirm before Phase 3:** D-I — **confirmed, Rev 4.**
> D-F, D-G and D-K were already RESOLVED by constraints this file carries —
> see their rows. All eleven decisions are settled; §5 proceeds as drafted.
>
> Precedent for this format: the sibling spec's §6 decision table
> (`docs/superpowers/specs/mcp-tool-usage-analyzer.md:494-540`), which used the
> same structure with rows marked **RESOLVED**.
>
> **Rev 2 (2026-08-22)** — revised against a `project-reviewer` pass: one
> blocking finding (`collect_per_session` missing `data_dir`), five concerns
> and three nits, all resolved in this file. **No decision row was resolved by
> that pass** — D-A…D-G remained OPEN. Changes: canonical helper-signature block
> added before Phase 0 step 1; F8 reworded and F9 added; T12 added; T5 patch
> target specified; Phase 3 closeout gate added.
>
> **Rev 3 (2026-08-22)** — revised against an adversarial `inquisitor` pass
> (verdict: *do not start Phase 0*, 4 blocking charges + 5 concerns). Every
> charge was re-verified against source before being accepted; two were
> **partly wrong on the facts** and are corrected in place rather than absorbed
> (see §2.5, §2.7 and D-I). Substantive changes:
>
> - **New §2.5** — the flag-on path costs **three** full transcript reads per
>   file, not two. New row **D-J** (single-pass merge inside
>   `tool_collection.py`) is the response; it saves strictly more IO than the
>   "fuse into `parse_sessions`" alternative inquisitor proposed, which §2.5
>   rejects with a specific reason.
> - **New §2.6 / new row D-H** — the Breakdown view owns a **live period
>   selector** (`layout-b-diag.js:986,1003-1009,1128`). A server-pre-aggregated,
>   timestamp-less `by_mcp_usage` structurally cannot respond to it. This is a
>   blocking placement question and **may flip D-D from (b) to (a)**.
> - **New §2.7 / new row D-I** — the Stop hook (`hooks/dashboard-regen.py`) is
>   how the dashboard is produced for opted-in users, and it passes no
>   `--track-mcp-calls`. D-E's discoverability rationale is corrected
>   accordingly.
> - **D-C=(a)** is no longer a "one-line fix": it breaks
>   `tests/test_dashboard_snapshot.py` and would export a number computed on
>   the wrong date bounds. The row now offers only two honest endpoints.
> - **T9/T12** no longer claim automated coverage of rendered DOM — there is no
>   JS execution capability in this repo (verified: no `package.json` anywhere;
>   dev deps are `ruff` + `pytest`, `pyproject.toml:14-18`).
> - **D-F and D-G marked RESOLVED** by §2.4 and N5 respectively; the stale note
>   claiming spec **D1 already answers D-G is corrected** — D1 settled *where
>   the flag lives*, not *what it gates*.
> - **New N6** — a numeric gate on the flag-**on** path (N5 only ever gated the
>   unfailable flag-off path), tied to the hook's hard 120 s subprocess timeout,
>   with its outcome wired to D-I's go/no-go.
> - **New §4.3 / new row D-K (RESOLVED)** — `by_mcp_usage`'s JSON shape is
>   written down. It is **not** identical to `tool-usage` stdout
>   (`cli/tool_usage.py:235-243`).
> - **Phase 2 is inverted.** Rev 2 documented D-D=(b) as the primary body while
>   recommending it; since D-H=(b) now flips the recommendation to D-D=(a), the
>   phase body was rewritten for D-D=(a) and the D-D=(b) surface demoted to the
>   alternative. Documenting one surface while recommending another is the same
>   defect as the Rev 2 `ctx` justification this revision also fixes.
>
> **Rev 4 (2026-08-23)** — all eight remaining OPEN decisions (D-A, D-B, D-C,
> D-D, D-E, D-H, D-I, D-J) confirmed directly by the user, one at a time via
> `AskUserQuestion`, not by an automated review pass. **Every confirmed choice
> matches this file's own Recommended column** — no rationale prose changed,
> only resolution markers were added to each row. Confirmed:
>
> - **D-A=(a)** — new `collect_per_session(...)` in `tool_collection.py`;
>   refactor `cli/tool_usage.py:189-233` to call it.
> - **D-J=(a)** — merge passes 2 and 3 into a single `collect_unit()`
>   `_iter_entries` scan.
> - **D-B=(a)** — session-scoped: in-window session-id set from
>   `result.sessions[*]`, whole-session tool-call counts, "whole-session
>   counts" label required.
> - **D-C=(b)** — add `by_mcp_usage` to both HTML and `--format json`; leave
>   `by_skill_adoption` untouched; file a follow-up issue naming both the
>   payload omission and the date-bounds bug.
> - **D-H=(b)** — flip to D-D=(a): a top-level tab, outside the period
>   selector's scope.
> - **D-D=(a)** — new top-level tab (`data-view="mcp"`), implied directly by
>   D-H's answer.
> - **D-E=(b)** — always render the tab, with empty-state copy naming how to
>   turn collection on (copy text is D-I-dependent, written last).
> - **D-I=(a)** — no hook change for v1; hook-generated dashboards show the
>   D-E empty state; file (b) (the `track_mcp_calls` userConfig toggle) as an
>   immediate follow-up issue.
>
> All eleven rows in §3 are now marked RESOLVED/CONFIRMED. §5's phases require
> no rework — they were already drafted against these recommendations.
>
> **Rev 5 (2026-08-24)** — caught during Phase 2 implementation, not a new
> development: the "`workflows/wf_*/` blind spot" premise carried by F7, §2.3
> and the Phase 3 closeout gate (item 3) was **already stale at Rev 4
> confirmation**. Commit `83010fe` ("fix: traverse subagents/workflows/wf_*/ in
> transcript walker (#255)", **Fixes #253**) merged 2026-08-22 19:10 — the same
> day as, and before, Rev 4's confirmation — and closed the gap: it extended
> `_walk_subagents` in `transcript_walker.py` to traverse
> `subagents/workflows/wf_*/` with the same agent_path construction, depth cap,
> cycle defense and warning machinery as ordinary `subagents/<agent_id>/`
> entries, fixing visibility for "all prospector output (token attribution,
> tool-usage, everything)" per its own commit message — not a
> tool-usage-specific fix. It also removed the stale
> `warnings.workflow_agents_unattributed` flag from `compute_tool_usage()`'s
> output and the corresponding README "Known gap" note. This was a gap in the
> planning process (Rev 4's confirmation pass did not re-verify §2.3 against
> the same-day merge), not a new development since Rev 4. Changes below are
> corrected in place at F7, §2.3 and the Phase 3 closeout gate item 3; no
> decision row is affected — no `by_mcp_usage` schema field or requirement
> depended on the stale blind-spot framing beyond the copy itself.
>
> **Rev 6 (2026-08-24)** — Phase 3 documentation work (README, spec
> reconciliation) completed. **D-I confirmed = (a)**: no hook code change —
> `hooks/dashboard-regen.py` continues to pass no `--track-mcp-calls`, and
> hook-generated dashboards show the D-E empty state. N6's G1/G2 placeholder
> thresholds (§4.2) are now replaced with real figures, measured on the
> maintainer's local corpus (1,798 transcript files, 796 MB):
> `dashboard --format json` took 4.62s with `--track-mcp-calls` off and 9.61s
> with it on (~2.08x). **G1 (≤45s) and G2 (≤3x) both pass.** Filing the
> follow-up issues and posting the resolved §3 decisions to #248 (Phase 3
> steps 3-4) are handled separately, not part of this revision.

---

## 1. What this is

Issue #195 shipped the MCP tool-usage **data layer**; #248 is the **dashboard
surface** for it. The spec records this split explicitly: its status line reads
"IMPLEMENTED (Phases 0–2); §8 Phase 3 remains open under #248"
(`docs/superpowers/specs/mcp-tool-usage-analyzer.md:26-29`), and its issue
boundary table assigns `renderer.py` / `templates/dashboard.html` /
`static/views/` to #248 (`:84-88`).

**What already exists and must be reused, not re-derived:**

| Asset | Location | Role here |
| --- | --- | --- |
| `compute_tool_usage()` | `src/claude_prospector/aggregator.py:303-425` | Pure aggregation. Returns `by_tool`, `by_server`, `by_agent`, `availability_signal`, `warnings`. No IO, no time filtering. |
| `collect_session()` | `src/claude_prospector/tool_collection.py` (called at `cli/tool_usage.py:212`) | Per-transcript tool-call + availability collection. |
| `normalize_mcp_tool_name()` | `src/claude_prospector/mcp_names.py` | Server/method resolver. Do not write a second one (spec §3, `:218-226`). |
| The per-session collection loop | `src/claude_prospector/cli/tool_usage.py:189-233` | Session filter → JSONL glob → `collect_session` → record filters → `per_session`. **This is the piece the dashboard needs and does not have** — see §2.1. |
| `_read_static()` | `src/claude_prospector/renderer.py:17-48` | Inlines a `static/` asset; works for both editable and wheel installs. |
| `AggregateResult` | `src/claude_prospector/aggregator.py:46-60` | Plain `@dataclass`, every `by_*` field a `field(default_factory=dict)`. A new `by_mcp_usage` follows verbatim. |

**Scope in one line:** gate a per-session MCP collection pass behind a new
`dashboard --track-mcp-calls` flag (default off), attach the
`compute_tool_usage()` output to `AggregateResult`, surface it in both the HTML
dashboard and `--format json`.

---

## 2. Corrections to inherited assumptions

Seven claims that were carried into this task's framing — four from the original
dispatch brief (§2.1–§2.4), three from the Rev 3 adversarial pass (§2.5–§2.7) —
do not survive contact with the shipped code. Each changes the plan.

### 2.1 The conditional-attach is ~45 lines of IO, not the 10-line skill-adoption pattern

The obvious framing is "mirror the skill-adoption block at
`cli/dashboard.py:169-179`". That block is 10 lines only because
`parse_skill_tracking()` (`cli/dashboard.py:170`) does all the IO and returns
ready-made event lists.

There is no equivalent for tool usage. The work sits inline in
`cli/tool_usage.py:189-233`: per-session repo/date filtering, a
`(data_dir / "projects").glob(f"*/{session.session_id}.jsonl")` lookup, a
`collect_session()` call with `OSError` handling, and per-record `--agent` /
`--tool` / `--server` filtering. Copy-pasting that into `dashboard.py` forks the
one piece of logic most likely to drift.

The glob is not incidental: the code comments it at `cli/tool_usage.py:200-202`
— "SessionRecord carries no JSONL path, so locate the file rather than
reconstructing the project slug". `SessionRecord` (`models.py:72-100`) indeed
has no path field. So either the shared helper keeps the glob, or
`SessionRecord` gains a path field. **D-A** resolves this.

### 2.2 `ToolUseRecord` has no timestamp — the panel cannot share the dashboard's denominator

`ToolUseRecord` (`models.py:135-152`) carries exactly four fields: `tool_name`,
`tool_use_id`, `agent_type`, `agent_path`. **No timestamp.**

This collides with how the dashboard filters. `aggregate()` filters
**per-message** on `msg.timestamp` (`aggregator.py:103-111`) and counts a
session as in-window if it has ≥1 in-window message (`:113-115`). `tool-usage`
filters **per-session** on `session.start_time`
(`cli/tool_usage.py:195-198`).

Consequence: a session straddling the window boundary contributes only its
in-window *tokens* to the dashboard, but its MCP tool calls are all-or-nothing.
The panel's numbers will sit on a different denominator from every other number
on the page unless this is decided deliberately. **D-B** resolves this.

### 2.3 `warnings.workflow_agents_unattributed` does not exist

Spec §7's sample envelope shows `"workflow_agents_unattributed": true`
(`docs/superpowers/specs/mcp-tool-usage-analyzer.md:600`), but the shipped
`compute_tool_usage()` emits only `{"malformed_mcp_names": ...}`
(`aggregator.py:422-424`), and `tests/test_aggregator_tool_usage.py:217`
actively asserts `"workflow_agents_unattributed" not in result["warnings"]`.
The spec sample is stale on this point.

**Consequence for the view — corrected in Rev 5.** The finding above (this key
was never in the shipped `compute_tool_usage()` output) still stands, but the
gap it would have reported does not: PR #255 / issue #253 (`83010fe`, merged
2026-08-22, same day as and before Rev 4's confirmation) extended
`_walk_subagents` in `transcript_walker.py` to traverse
`subagents/workflows/wf_*/` with the same agent_path construction, depth cap,
cycle defense and warning machinery as ordinary `subagents/<agent_id>/`
entries — fixing visibility for "all prospector output (token attribution,
tool-usage, everything)" per its own commit message, not just this feature.
That same PR removed `warnings.workflow_agents_unattributed` from
`compute_tool_usage()`'s output, so the missing key this section documents is
now explained by two independent facts: it was never in the spec-implied
shape, **and** the underlying gap it would have reported is closed. **F7
(corrected)** governs what the panel's copy must say instead — a bounded scope
statement, not a completeness claim, since `_walk_subagents`'s own contract
still skips transcripts past its path-depth cap, missing JSONL, cycles, or
`OSError`.

### 2.4 `--compact` is a payload-size question, not a parity question

The dashboard HTML is **self-contained**: `data` is serialised and inlined into
every generated file as `window.DATA` (`renderer.py:100-101`,
`templates/dashboard.html:283`). The spec's own concern that "~50 agents × ~250
tools makes the default dict dominate the payload"
(`docs/superpowers/specs/mcp-tool-usage-analyzer.md:527-529`) is strictly worse
here than for CLI stdout, because the bytes are written to disk on every run.

So the question is not "should the dashboard mirror `tool-usage --compact`" but
"does the dashboard need `by_agent` at all". **D-F** resolves this.

### 2.5 The flag-on path costs *three* full transcript reads, not two — and fusing the walks is the wrong fix

D-G's rationale (and Rev 2's framing generally) said collection "roughly
doubles" transcript IO. That undercounts. Per transcript file, with the flag on:

| Pass | Where | What it reads |
| --- | --- | --- |
| 1 | `parser._parse_jsonl_messages` (`parser.py:316-373`, driven from `_parse_session`'s walk at `parser.py:440`) | whole file |
| 2 | `tool_collection.collect_tool_uses` (`tool_collection.py:81`, via `_iter_entries`) | whole file |
| 3 | `tool_collection.collect_availability` (`tool_collection.py:148`, via `_iter_entries`) | whole file |

`collect_session` (`tool_collection.py:205-211`) calls both visitors per unit, so
**the second walk is itself two passes.** On top of that, `walk_session` runs
twice per session (`parser.py:440` and `tool_collection.py:205`) and
`cli/tool_usage.py:203-205` globs `projects/*/{session_id}.jsonl` once per
session.

**The proposed remedy — fuse tool collection into `parse_sessions`' existing
walk — is rejected, for three specific reasons:**

1. **It forks the collection path instead of unifying it.** `tool-usage` filters
   `--repo` and `--from`/`--to` on `SessionRecord` **after** parsing and
   **before** collecting (`cli/tool_usage.py:192-215`). Fusion moves collection
   to *before* session selection, so `tool-usage` would either regress (collect
   for every session on disk, then discard) or keep its own separate path. Two
   collection paths is the exact failure D-A exists to prevent.
2. **It saves no file reads.** Fusion shares the *walk*, not the *read*: passes
   2 and 3 above still open the file independently, because they live in
   `collect_tool_uses` / `collect_availability`, not in `walk_session`. The
   saving is one directory traversal per session — real but an order of
   magnitude smaller than one file read per transcript.
3. **The shipped design is deliberately two visitors, and PR #250's docstrings
   say so.** `transcript_walker.py:5-11` — "Consumers drive the walker with
   their own visitor: `parser` turns each unit into `MessageRecord` objects,
   `tool_collection` turns the same units into tool-call and MCP-availability
   records." `tool_collection.py:3-4` — "This is the **second visitor** over
   `transcript_walker` (the first being `parser`)." The extraction shared the
   traversal *code*; it did not promise a single traversal. (This is supporting
   evidence, not the argument — reasons 1 and 2 stand on their own.)

**The better fix, which the fusion proposal would have missed: merge passes 2
and 3.** They are two independent forward scans of the same entries —
`collect_tool_uses` keys on `entry["type"] == "assistant"`, `collect_availability`
on `entry["type"] == "attachment"` — so one `_iter_entries` loop with two
branches produces both. That removes a whole file read per transcript (3 → 2,
≈33% of the flag-on read cost), which is strictly more than fusion saves, with a
blast radius contained inside one module that already has a unit-test harness
(`tests/unit/test_tool_collection.py`). **D-J** resolves this.

> **Trap if D-J=(a) is taken.** `collect_session` appends one
> `AgentAvailability` per unit **unconditionally** (`tool_collection.py:208-210`)
> — including units where no attachment entry was ever seen, which yield
> `signal_present == False` (`models.py:177`). `compute_tool_usage` derives
> `sessions_without_signal` and the `sessions_seen_in: null`-vs-`0` distinction
> from exactly those empty records (`aggregator.py:311-319,350-354,391-399`). A
> merged loop that emits an availability record only when an attachment was
> observed silently converts `null` into `0` — i.e. it breaks **F6**, the
> load-bearing distinction this panel exists to show.

### 2.6 The panel cannot honour the Breakdown view's period selector

Under the recommended D-D=(b) the panel lands inside `renderLayoutBDiag`, which
owns a **live client-side period selector**: `state.period` defaults to `'7d'`
(`static/views/layout-b-diag.js:986`), the buttons `5h / 24h / 7d / 30d / All`
re-run `compute()` on click (`:1003-1009`, `:1177`), every derived value is
re-filtered through `CP.filterSessions(window.DATA.sessions, state.period)`
(`:990`), and the page header renders "Where your tokens went · this
`${state.period}`" (`:1128`).

`by_mcp_usage` is aggregated **server-side**, over whatever window the CLI run
used, from records that carry no timestamp (§2.2). It therefore **cannot
re-filter on click**. A user who clicks "5h" would watch every number on the page
change except the MCP panel's — with no visible reason why.

This is a placement problem, not a copy problem, and it is why **D-H** may flip
**D-D**. It also subsumes the separate question of what the panel's scope label
says on the default all-time path (`--from`/`--to`/`--window` all default to
`None`, `cli/dashboard.py:83-99`), which is a *third* distinct time basis
alongside "this 7d" (the selector default) and "the CLI window".

### 2.7 The dashboard most users see is produced by a Stop hook that passes no flags

`hooks/dashboard-regen.py` is registered as a `Stop` hook
(`hooks/hooks.json:24-38`) and runs

```
<venv python> -m claude_prospector dashboard --output <path> --no-open
```

inside `subprocess.run(..., timeout=120)` (`hooks/dashboard-regen.py:581-594`).
No `--window`, no `--from`, and — as written — no `--track-mcp-calls`.

Two corrections to how this was put to the plan, both verified:

- **It is not unconditional.** The hook returns 0 immediately unless plugin
  setup state is `VALID` (`:490-500`) **and** the `autoregen` user-config
  toggle is truthy (`:510-526`); `autoregen` defaults to `false`
  (`.claude-plugin/plugin.json:13-20`). So this path exists only for users who
  opted in — but for those users it is *the* dashboard.
- **A 120 s timeout does not write the failure page.** `_write_page(dashboard,
  _regen_failed_page(...))` fires only on a non-zero **exit code** (`:596-598`).
  `subprocess.TimeoutExpired` is an exception, caught by the outer
  `except Exception` at `:607`, which writes one line to stderr and returns 0.
  The dashboard file is left untouched.

  **The real timeout risk is worse than the failure page, and is new
  information:** `render()` writes with a plain, non-atomic
  `output_path.write_text(html, encoding="utf-8")` (`renderer.py:125`). A
  subprocess killed mid-write leaves a **truncated HTML file** — a broken
  dashboard with no error page and no log line explaining it. Any change that
  moves the hook's runtime materially closer to 120 s raises the odds of that
  outcome. **D-I** and **N6** address it.

Consequence for **D-E**: its stated rationale — "discoverability is the point: a
hidden tab means nobody learns the flag exists" — is false as written for
autoregen users. If the hook never passes the flag, those users see the
empty-state copy **permanently**, and the tab teaches them about a flag they
have no way to pass without abandoning the hook and hand-running the CLI. The
rationale is repaired in D-E and the underlying question moved to **D-I**.

---

## 3. Decisions (all RESOLVED)

Ranked by the phase each one gated. **D-A and D-J blocked Phase 0; D-B and D-C
blocked Phase 1.**
**D-F, D-G and D-K were RESOLVED** — not by a reviewer's opinion, but by
constraints this file already carries (§2.4, N5, and D-F-plus-§4.3
respectively); their rows record the excluding constraint so the question is
not silently reopened. **The remaining eight rows (D-A, D-B, D-C, D-D, D-E,
D-H, D-I, D-J) were confirmed directly by the user (Rev 4, 2026-08-23) — see
the Rev 4 changelog entry above for the full list of confirmed choices.**

| # | Question | Options | **Recommended** | Gates |
| --- | --- | --- | --- | --- |
| **D-A** | Where does the shared per-session collection loop live? | (a) New `collect_per_session(...)` in `tool_collection.py`; refactor `cli/tool_usage.py:189-233` to call it. (b) Copy the loop into `cli/dashboard.py`. (c) New `cli/_mcp_usage.py` helper module. (d) Add a JSONL-path field to `SessionRecord` so no glob is needed. | **CONFIRMED = (a) (Rev 4)** — one owner for the glob + `OSError` handling, and `tool_usage.py`'s existing tests become the regression harness for the extraction. (d) is a `models.py`/`parser.py` change with much wider blast radius; keep the glob for now. **Deliberate tradeoff, not scope creep:** (a) widens `tool_collection.py` from pure *transcript-level* collection into *data-directory topology* knowledge — it must now know that transcripts live at `{data_dir}/projects/{slug}/{uuid}.jsonl`. That boundary erosion is accepted knowingly, in exchange for a single owner of the glob. (c) (`cli/_mcp_usage.py`) is the alternative that preserves the boundary at the cost of a third module; revisit (c) if `tool_collection.py` accumulates more filesystem-layout logic. **(e) — fusing collection into `parse_sessions`' existing walk so one pass produces both record families — was evaluated in Rev 3 and rejected: it forks the collection path (`tool-usage` filters between parse and collect), and it saves a directory traversal rather than a file read. Full reasoning and the better alternative are in §2.5 / D-J.** | Phase 0 |
| **D-B** | How is the MCP panel time-filtered, given `ToolUseRecord` has no timestamp (§2.2)? | (a) **Session-scoped**: take the in-window session-id set straight from `result.sessions[*]["session_id"]` (`aggregator.py:150-153`), collect whole-session tool calls for exactly those sessions, and label the panel "whole-session counts for sessions active in this window". (b) Add `timestamp` to `ToolUseRecord` and filter per call. (c) Include only sessions wholly inside the window. | **CONFIRMED = (a) (Rev 4)** — the session denominator then matches `result.total_sessions` exactly, with zero model changes. (b) costs a `models.py` + `tool_collection.py` + fixture change and still cannot time-filter the availability deltas, which spec F7a (`:423-426`) requires be session-scoped anyway. (c) silently drops the longest sessions, which are the heaviest MCP users. **The "whole-session counts" label is not optional under (a)** — without it the panel silently disagrees with the token numbers beside it. **Rev 3:** that label is necessary but not sufficient. It describes the *session* basis; it says nothing about the *time* basis, which on a default run is all-time (`cli/dashboard.py:83-99`) and on the Breakdown view sits next to a live "this 7d" header. See **F10** for what the label must actually say, and **D-H** for the placement question underneath it. | Phase 1 |
| **D-C** | `--format json` parity. `cli/dashboard.py:200-215` builds `payload` independently of `renderer.py:87-98`'s `data`, and already omits `by_skill_adoption` even though `result.by_skill_adoption` is set (`:174`). | (a) **REWRITTEN in Rev 3 — see the D-C box below.** Add `by_mcp_usage` to both surfaces **and** fix `by_skill_adoption` properly: payload key + the date-bounds bug + a reviewed snapshot re-capture. (b) Add `by_mcp_usage` to both, leave `by_skill_adoption` alone and file it as a follow-up issue. (c) HTML only. | **CONFIRMED = (b) (Rev 4)** — changed from (a) in Rev 3. It is not a one-line fix (see box); it drags in a wrong-denominator bug and a deliberate payload-contract change, neither of which belongs bundled into a feature PR. (a) is acceptable **only** in its rewritten, three-part form. | Phase 1 |
| **D-D** | UI placement. | (a) New top-level tab (`data-view="mcp"`) beside Overview/Breakdown/Advanced (`templates/dashboard.html:306-317`). (b) New entry in the `TAB_DEFS` registry inside the Breakdown view (`static/views/layout-b-diag.js:881-886`). (c) New card in Breakdown's `secondary()` next to the existing Skills panel (`:1033-1051`). | **CONFIRMED = (a) (Rev 4 — D-H resolved to (b), which flips this row's base recommendation from (b) to (a); see the D-H row).** The base recommendation was **(b), but conditional on D-H.** `TAB_DEFS` is a 4-row registry of `{id, icon, label, build}`; adding a fifth is a one-line insertion plus a `build` function, and it inherits the view's existing CSS, period tabs and state handling. (a) costs a new `_read_static` kwarg, a new `<script>` tag, a `.view-toggle` button, a `_VIEW_SUBS` entry and a `_renderView` branch (`templates/dashboard.html:293-296,306-317,330-357`). **Rev 3: the inherited "period tabs and state handling" is now a liability, not a benefit — §2.6. If D-H resolves that the panel must not sit under a selector it cannot obey, D-D flips to (a). Decide D-H first.** | Phase 2 |
| **D-E** | What renders when `--track-mcp-calls` is off (the default) and `by_mcp_usage` is `{}`? | (a) Hide the tab entirely via a Jinja conditional on a `has_mcp` flag. (b) Always render, with empty-state copy naming how to turn collection on. | **CONFIRMED = (b) (Rev 4)** — with the **rationale corrected in Rev 3**. The old rationale ("a hidden tab means nobody learns the flag exists") is false for autoregen users: their dashboard comes from the Stop hook, which passes no flags (§2.7), so under D-I=(a) they see the empty state *permanently* and cannot act on copy that only names a CLI flag. (b) still wins, for a different reason: hiding the tab makes the feature undiscoverable for **everyone**, whereas an honest empty state is at worst inert. **The copy is therefore D-I-dependent and must be written last:** under D-I=(a) it must say "re-run `claude-prospector dashboard --track-mcp-calls` from the CLI — the automatic session-end regeneration does not collect this data"; under D-I=(b) it must name the plugin-manager toggle instead. Do not ship copy that names only the CLI flag if D-I=(b) is chosen. | Phase 2 |
| **D-F** | Does the dashboard payload carry `by_agent` (§2.4)? | (a) Omit `by_agent`; the panel renders `by_server` + `by_method` + `availability_signal` only. (b) Always store the compact shape (`compute_tool_usage(..., compact=True)`). (c) Expose a `--compact` dashboard flag mirroring `tool-usage`. | **RESOLVED = (a)** (Rev 3). Excluded by constraints already in this file, not by preference: **(c)** is excluded by §2.4 — it puts a user-facing flag on a payload-size concern the user should not have to reason about, on a surface where the bytes are written to disk on every run. **(b)** is excluded because **no requirement in §4.1 consumes `by_agent` in any shape** — F5 needs `by_server[*].by_method` (`aggregator.py:400-408`), F6 needs `sessions_seen_in`, F9 needs `warnings`. Storing a compact `by_agent` is dead payload in every generated file. If per-agent MCP attribution is wanted later it arrives as a new requirement, and `compact=True` is already a supported argument (`aggregator.py:303-306`) — the upgrade stays cheap. | Phase 2 |
| **D-G** | Does `--track-mcp-calls` gate **collection** (IO) or only **display**? | (a) Gates collection: flag off ⇒ zero extra transcript reads. (b) Always collect, gate rendering. | **RESOLVED = (a)** (Rev 3), by **N5**, which this file already states: "no measurable runtime regression on `dashboard` with the flag off". Under (b) every flag-off run pays two extra full reads per transcript (§2.5) — a guaranteed, measurable regression. N5 and (b) cannot both hold, so (b) is excluded arithmetically rather than by taste. **Correction to the record:** a Rev 2-era note held that spec **D1** already resolved this. It does not. D1 (`docs/superpowers/specs/mcp-tool-usage-analyzer.md:494-540`) settled **where the flag lives** — on `dashboard`, not `tool-usage` — and says nothing about whether it gates collection or display. Do not cite D1 for this row. | Phase 1 |
| **D-H** | The panel sits inside a view with a **live period selector** it structurally cannot obey (§2.6). How is that reconciled? | (a) Keep D-D=(b) and add an explicit, data-driven scope line inside the panel — e.g. "MCP counts cover **all N sessions in this dashboard's data range** and do not change with the period buttons above" — rendered from the `window` block in the payload (see D-K schema). (b) Flip to **D-D=(a)**: a top-level tab, outside the period-selector's scope, where no live control implies filtering the panel cannot do. (c) Make the panel period-aware by emitting per-session MCP counts so the client can re-aggregate on click. | **CONFIRMED = (b) (Rev 4)** — flip D-D to (a). §2.6 is a structural mismatch, and (a) removes it instead of apologising for it in copy that most users will not read. The cost is the known D-D=(a) surface (5 small edits in `templates/dashboard.html` + `renderer.py`) and the `_renderView` catch-all trap already documented in Phase 2. **(c) is rejected** — it re-introduces the payload bloat §2.4 exists to prevent (per-session × per-server counts inlined into every generated HTML file) and it still cannot period-filter the availability deltas, which spec F7a (`:423-426`) requires be session-scoped. **(a) is the fallback** if the D-D=(a) surface cost is judged too high for v1; if taken, the scope line is **not optional** (same standing as D-B's "whole-session counts" label). | Phase 2 — **decide before D-D** |
| **D-I** | The Stop hook (`hooks/dashboard-regen.py:581-594`) regenerates the dashboard for autoregen users and passes no `--track-mcp-calls` (§2.7). Does that change? | (a) **No hook change.** The panel is CLI-opt-in in v1; hook-generated dashboards show the D-E empty state, and the copy says so explicitly. (b) **New `track_mcp_calls` boolean in `userConfig`** (`.claude-plugin/plugin.json:13-20`, exactly mirroring `autoregen`), substituted into `hooks/hooks.json:24-38` as `${user_config.track_mcp_calls}`, parsed by the hook's existing `_parse_autoregen_arg` truthy helper (`:162-179`) and used to conditionally append the flag to the subprocess argv. (c) Hook always passes `--track-mcp-calls`. | **CONFIRMED = (a) (Rev 4), for v1, with (b) filed as an immediate follow-up issue.** **(c) is rejected outright:** it puts two extra full transcript reads per file (§2.5) on the synchronous turn-end path under a hard 120 s timeout, unconditionally, for every autoregen user — including the ones who never open the MCP panel. That is D-G=(b)'s cost with the blast radius moved somewhere worse. **(b) is the right end state** but it spans `plugin.json` + `hooks.json` + the hook script + `tests/test_dashboard_regen_hook.py`, and it must not ship before N5's flag-on measurement exists — the whole point of the toggle is that a user can enable something whose cost is known to fit inside 120 s. **(a) is honest in the meantime** provided D-E's copy names the limitation instead of implying the flag is reachable from the hook. | Phase 3 (Phase 1 if (c)) |
| **D-J** | Do passes 2 and 3 (`collect_tool_uses` + `collect_availability`, §2.5) merge into a single `_iter_entries` scan? | (a) Yes — add a `collect_unit(unit) -> tuple[list[ToolUseRecord], AgentAvailability]` in `tool_collection.py`, one loop with an `assistant` branch and an `attachment` branch; `collect_session` calls it once per unit. Keep `collect_tool_uses` / `collect_availability` as public wrappers so existing callers and tests are untouched. (b) No — leave the two passes; accept 3 reads per transcript. | **CONFIRMED = (a) (Rev 4)** — it is the largest IO saving available (≈33% of the flag-on read cost) for the smallest blast radius (one module, one existing test file), and unlike the rejected fusion (§2.5) it benefits `tool-usage` and `dashboard` equally. Sequence it as **Phase 0 step 5, a second behaviour-preserving refactor commit**, gated the same way: `tests/unit/test_tool_collection.py` and `tests/test_aggregator_tool_usage.py` must pass **unmodified**. **Do not skip the §2.5 trap box** — the merged loop must still emit an `AgentAvailability` for units with no attachment entries, or F6 breaks silently. Choose (b) if Phase 0 is judged already large enough; the cost is that N5's flag-on number lands ~50% higher, which matters directly to D-I. | Phase 0 |
| **D-K** | What exactly is the JSON shape of `by_mcp_usage`? | (a) Identical to `tool-usage` stdout. (b) A named subset: `compute_tool_usage()`'s output **minus** `by_agent` (D-F), **plus** `warnings.unreadable_transcripts` and a `window` block. (c) An independent shape designed for the panel. | **RESOLVED = (b)** — spelled out in §4.3, and resolved by the same test applied to D-F/D-G: the alternatives are excluded by constraints this file already carries. **(a)** is excluded by **D-F=(a), itself RESOLVED** — `tool-usage` stdout keeps `by_agent` and adds a `compact` key (`cli/tool_usage.py:235-243`), so "identical" re-imports exactly the payload bloat D-F just removed, plus a flag that does not exist on this surface. **(c)** is excluded because every field the panel needs already exists under a settled name in `compute_tool_usage`'s return (`aggregator.py:410-425`); a second vocabulary for the same data is cost with no requirement behind it. What remains — (b) — is not a choice so much as the residue. | Phase 1 |

### D-C in detail — why "one line" was wrong

Rev 2 called the `by_skill_adoption` payload fix "one line". Rev 3 verified it
and it is not. Three findings, each verified by read:

1. **It breaks a golden-snapshot test that is not in the original `touches:`
   list.** `tests/test_dashboard_snapshot.py:76` asserts **full-dict equality**
   of `dashboard --format json` output against
   `tests/fixtures/dashboard_snapshot_pre_refactor.json`, normalising only
   `generated_at` (`:72-74`). The fixture's top-level keys are exactly
   `generated_at, total_tokens, total_messages, total_sessions, by_model,
   by_agent, by_skill, by_project, by_day, sessions, limits`. Adding
   `by_skill_adoption` **unconditionally** adds a twelfth key — the fixture tree
   (`tests/fixtures/session_summaries/dashboard_baseline_input/`) contains one
   JSONL file and no skill-tracking log, so the value would be `{}` and the test
   would still fail on the added key. The failure message
   (`:76-80`) instructs the reader to "re-capture the snapshot", which is
   exactly the reflex that turns a deliberate contract change into an
   unreviewed one.
2. **The number it would export is computed on the wrong date bounds.**
   `cli/dashboard.py:174-179` calls `compute_skill_adoption(..., from_date=args.from_date,
   to_date=args.to_date)` — **raw argparse values**. But `aggregate()` resolves
   `--window` into `from_date` **internally** (`aggregator.py:94-96`:
   `from_date = now - timedelta(hours=window_hours); to_date = None`), so
   `args.from_date` is still `None` on any `--window` run. On
   `dashboard --window 7d`, every token number is 7-day-scoped and
   `by_skill_adoption` is **all-time**. Exporting that to `--format json`
   publishes a known-wrong denominator to consumers.
   *(Note: the snapshot test passes explicit `--from`/`--to` (`:50-55`), so the
   bug does not manifest there. The two problems are independent — fixing the
   bounds does not fix the snapshot, and re-capturing the snapshot does not fix
   the bounds.)*
3. **The same bug class is one edit away from being repeated here.** If
   `by_mcp_usage` carries a `window` block (D-K / §4.3), the dashboard must
   resolve `--window` into bounds *itself* or it will stamp `"start": null` on
   a windowed run. **Mitigation, mandatory under either D-C option:** compute
   the resolved bounds **once** in `cli/dashboard.py run()` and pass the same
   pair to `aggregate()` and to the MCP block. Do not duplicate
   `aggregator.py:94-96` inline.

**Therefore only two endpoints are acceptable. Anything between them is
prohibited.**

- **D-C=(b) — recommended.** Ship `by_mcp_usage` on both surfaces (gated per F4
  / F8). Leave `by_skill_adoption` untouched. **File a follow-up issue that
  names both halves explicitly**: the payload omission *and* the
  `args.from_date`-vs-resolved-bounds bug, with a warning that adding the key
  without fixing the bounds ships a wrong number. Add the issue number to the
  Phase 3 closeout gate.
- **D-C=(a) — acceptable only in full.** All three in one PR, as its own
  commit: (i) add the payload key, (ii) fix the date bounds so the exported
  number is right, (iii) re-capture the snapshot **as a reviewed
  payload-contract change** — the PR body must state the before/after key set
  and say that the snapshot diff was inspected, not regenerated on a red test.
  `tests/test_dashboard_snapshot.py` and its fixture move from "not mentioned"
  to declared `touches:` (already done in Rev 3).

> **Prohibited middle:** adding `by_skill_adoption` to `payload` *conditionally*
> (only when non-empty) so the snapshot stays green, without fixing the bounds.
> It looks like the cheapest option and is the worst one — it keeps the test
> green while shipping the wrong number, and it invents a sometimes-present key
> in a consumer contract with no flag to explain it.

**Not asked — already decided.** D7 (token cost per MCP call) is **OUT OF
SCOPE**, per the repo owner's 2026-08-22 comment on #248 and spec D7
(`docs/superpowers/specs/mcp-tool-usage-analyzer.md:508`). No token-cost proxy
in this pass; record as a follow-up issue if still wanted after the panel ships.

---

## 4. Requirements

### 4.1 Functional

- **F1** New `--track-mcp-calls` flag on the `dashboard` subparser
  (`cli/dashboard.py:64-139`), `action="store_true"`, default `False`.
- **F2** When the flag is set, `dashboard` collects per-session tool-use and
  availability records for the in-window sessions and assigns
  `compute_tool_usage(...)` output to a new `AggregateResult.by_mcp_usage`
  field.
- **F3** When the flag is not set, no transcript is re-read and
  `by_mcp_usage` stays `{}` (D-G).
- **F4** `by_mcp_usage` appears **unconditionally** in `renderer.py`'s `data`
  dict (`:87-98`, internal surface) and **only under the flag** in
  `cli/dashboard.py`'s `payload` (`:201-213`, consumer contract) — subject to
  D-C. The asymmetry is why F8 holds for `--format json` but **not** for the
  HTML path; see F8 and Phase 1 step 4.
- **F5** The panel renders, at minimum: per-server call volume, per-method
  drill-down from `by_server[*].by_method`, and the available-but-unused case
  (`total_calls: 0` with a non-null `sessions_seen_in`), which is the
  dormant-server prune signal the field exists for (spec §2.3, `:171-194`).
- **F6** `sessions_seen_in: null` must render as "unknown / not observable",
  **never as `0`**. The distinction is load-bearing and documented at
  `aggregator.py:311-319`.
- **F7** **Corrected in Rev 5 — see §2.3.** The panel carries static copy
  stating the *scope* of what its counts include — not a "blind spot" caveat,
  since PR #255 / issue #253 (`83010fe`) closed that gap before this view was
  written. Phrase it as a bounded scope statement, not a completeness claim:
  `_walk_subagents`'s own contract still skips transcripts past its path-depth
  cap, missing JSONL, cycles, or `OSError`, so "included" is not "every
  possible transcript, no exceptions." The panel also carries, under D-B=(a),
  the "whole-session counts" scoping label.
- **F10** The panel states its **time basis** from data, not from hardcoded
  copy: read `by_mcp_usage.window.start` / `.end` (§4.3) and render "all time"
  when both are `null` — which is the **default** `dashboard` invocation, since
  `--from`, `--to` and `--window` all default to `None`
  (`cli/dashboard.py:83-99`) and the Stop hook passes none of them
  (`hooks/dashboard-regen.py:581-594`). Under **D-H=(a)** this copy must also
  say the panel does not respond to the period buttons; under **D-H=(b)** the
  panel is outside the selector's scope and only the time basis is stated.
  Three different time bases exist on this page (§2.6) — the panel names its
  own rather than letting the reader infer it from the header.
- **F8** With the flag absent, output is byte-identical **for `--format json`
  consumers** — the key is omitted entirely, not emitted as `{}`. The HTML path
  is **not** byte-identical: `window.DATA` gains `by_mcp_usage: {}`
  unconditionally (F4), which the view JS handles as the D-E empty state. This
  asymmetry is deliberate — `window.DATA` is an internal surface, `--format
  json` is a consumer contract. Both carve-outs apply on top: the HTML `{}`
  injection above, and the D-C `by_skill_adoption` payload fix if chosen.
- **F9** When `by_mcp_usage["warnings"]["unreadable_transcripts"] > 0`, the
  panel renders a visible banner — e.g. "N sessions skipped — transcript
  unreadable. Counts below are incomplete." Without it, an unreadable-transcript
  run silently under-reports. This is the **flag-on-but-partial** state and is
  distinct from D-E's **flag-off** empty-state copy, which does not cover it;
  the two can never appear together (flag off ⇒ no collection ⇒ `skipped`
  absent). Counts still render alongside the banner — it is a caveat, not a
  replacement for the panel.

### 4.2 Non-functional

- **N1** Read-only; no new runtime dependency (spec N1/N2, `:468-469`).
- **N2** Google-style docstrings, full type hints (spec N4, `:473-476`).
- **N3** Privacy: tool **names and counts only**; no `tool_use.input` payloads
  (spec N6, `:487-490`). `ToolUseRecord` structurally cannot carry them.
- **N4** Lint gate is **both** `uv run ruff check .` **and**
  `uv run ruff format --check .` (CLAUDE.md § CI gates — `ruff check` alone
  missed an unformatted file and failed CI on PR #225).
- **N5** **Flag off — no measurable runtime regression.** The spec's own N5
  precedent (`:477-481`) is a before/after `dashboard --format json` run on the
  local corpus. This path cannot regress by construction under D-G=(a) (the
  lazy import and the collection block are both inside
  `if args.track_mcp_calls:`), so the measurement is a guard against
  accidental hoisting, not a real risk.
- **N6** **Flag on — a hard numeric ceiling, because one exists in the system.**
  The Stop hook runs `dashboard` inside `subprocess.run(..., timeout=120)`
  (`hooks/dashboard-regen.py:581-594`), and a kill at 120 s leaves a
  **truncated** `dashboard.html` with no error page, because `render()` writes
  non-atomically (`renderer.py:125`; full reasoning in §2.7). That 120 s is the
  only hard limit in the system, so the flag-on path is gated against it:

  | Gate | Threshold | When |
  | --- | --- | --- |
  | G1 | `dashboard --track-mcp-calls --format json` on the **full local corpus** completes in **≤ 45 s** wall-clock | End of Phase 1, recorded in the PR body |
  | G2 | Flag-on wall-clock is **≤ 3×** the flag-off baseline on the same corpus | End of Phase 1, same run |
  | G3 | If G1 lands in **45–90 s**: **D-I=(b) is blocked.** Ship D-I=(a); the hook must not be able to enable the flag at all | Phase 3 |
  | G4 | If G1 **exceeds 90 s**: stop. The feature does not ship enabled-by-hook in any form, and Phase 2 should reconsider whether collection needs a `--limit`/`--since` bound of its own before the panel ships | Phase 1 |

  **Provenance of these numbers — read before treating them as measurements.**
  They are **placeholders**, not observations. The session that produced Rev 3
  had no shell tool available, so the local corpus was never sized and nothing
  was timed. The executor **must** replace them with real figures at the end of
  Phase 1 and record corpus size (session count, transcript-file count, total
  MB) alongside, so the thresholds can be recalibrated rather than re-guessed.
  The 45 s figure is chosen as ~⅓ of the hook's timeout to leave headroom for a
  cold filesystem cache and a slower machine; 90 s is the point past which a
  single slow run realistically hits the kill. What is **not** negotiable is
  that a number gates D-I — "documented as a cost" is what Rev 2 said, and a
  documented cost cannot be exceeded because nothing checks it.

### 4.3 `by_mcp_usage` — the exact JSON shape (D-K)

Neither Rev 1 nor Rev 2 wrote this down, and `tool-usage`'s stdout is **not** the
same shape. Verified difference: `cli/tool_usage.py:235-243` takes
`compute_tool_usage(..., compact=args.compact)` and then adds `window` and
`compact` and sets `warnings["unreadable_transcripts"]`. The dashboard drops
`by_agent` (D-F) and has no `compact` concept (D-F excluded the flag).

```jsonc
{
  "by_tool":  { "<tool_name>": <int> },          // from compute_tool_usage
  "by_server": {                                  // from compute_tool_usage
    "<server>": {
      "total_calls": <int>,
      "sessions_seen_in": <int|null>,            // null = unknown (F6)
      "sessions_used_in": <int>,
      "avg_calls_per_active_session": <float|null>,
      "by_method": { "<method>": <int> }
    }
  },
  "availability_signal": {                        // from compute_tool_usage
    "sessions_with_signal": <int>,
    "sessions_without_signal": <int>,
    "sources": [ "<attachment_type>" ],
    "by_server_sources": { "<server>": [ "<attachment_type>" ] }
  },
  "warnings": {
    "malformed_mcp_names": <int>,                // from compute_tool_usage
    "unreadable_transcripts": <int>              // added by cli/dashboard.py
  },
  "window": {                                     // added by cli/dashboard.py
    "start": "<YYYY-MM-DD>|null",                // RESOLVED bounds, not raw args
    "end": "<YYYY-MM-DD>|null",
    "sessions": <int>,
    "sessions_skipped": <int>
  }
}
```

Rules:

- **`by_agent` is omitted entirely** (D-F=(a) RESOLVED). Not `{}` — absent.
- **`compact` is omitted entirely.** It describes a `tool-usage` flag that does
  not exist on `dashboard`.
- **`window.start` / `window.end` are the resolved bounds**, mirroring
  `aggregator.py:94-96`'s `--window` → `from_date` resolution. Compute them
  once in `run()` and pass the same pair to `aggregate()` and here — this is
  the D-C finding-3 mitigation and it is mandatory. `null`/`null` means
  all-time, which is the default and the hook's path, and drives F10's copy.
- **`window.sessions` is the D-B=(a) denominator** — `len(per_session)`, which
  must equal `result.total_sessions` (T10 asserts it).
- The four `compute_tool_usage` keys are copied through **verbatim**; do not
  rename, flatten or re-key them. The spec's §7 sample envelope shows a
  `warnings.workflow_agents_unattributed` key — that key is stale and never
  emitted (§2.3). Do not add it to this schema.
- Reconciliation with the spec: spec §8 Phase 3 (`:694-702`) sketches this
  field but does not fix its shape. Phase 3 step 2 updates the spec to record
  the shape above as shipped, including the deliberate `by_agent` /`compact`
  omissions.

---

## 5. Phases

One PR per phase, each from its own worktree under `.worktrees/<branch>` per
CLAUDE.md § Worktrees. Never commit to `main`.

### Phase 0 — extract the shared collection helper (pure refactor)

**Depends on: D-A, D-J.**

#### The helper signature — single source of truth

Every reference to `collect_per_session` in this plan resolves to exactly this
signature. Do not restate a partial shape elsewhere; amend here instead.

```python
def collect_per_session(
    sessions: list[SessionRecord],
    data_dir: Path,
    *,
    agent: str | None = None,
    tool: str | None = None,
    server: str | None = None,
) -> tuple[list[tuple[str, list[ToolUseRecord], list[AgentAvailability]]], int]:
    ...
```

- **`sessions`** — already selected by the caller (step 2). The helper applies
  no `--repo` and no date filtering.
- **`data_dir`** — **required, not optional.** The helper owns the
  `(data_dir / "projects").glob(f"*/{session.session_id}.jsonl")` lookup
  (`cli/tool_usage.py:200-202`), so without it the helper structurally cannot
  locate a transcript. Both call sites pass `args.data_dir`.
- **Return** — `(per_session, skipped)`: the first element is the exact shape
  `compute_tool_usage` consumes (`aggregator.py:303-306`); `skipped` is the
  count of sessions whose transcript raised `OSError` or was not found.
- **`tool` and `server` are mutually exclusive — a caller-side contract, not
  validated by the helper.** `cli/tool_usage.py:224-231` binds them as
  `if args.tool is not None: … elif args.server is not None: …` — an `elif`,
  not two independent `if`s — so today `tool` **takes precedence** and `server`
  is silently ignored when both are supplied. Phase 0 is a behaviour-preserving
  refactor (T1 / spec N7), so the helper must **reproduce that precedence
  verbatim**. Do **not** add a `ValueError` when both are passed — raising
  would be a user-visible behaviour change smuggled into a pure refactor. (The
  reviewer finding that prompted this note called the risk "silent union
  behaviour"; the actual shipped failure mode is silent *precedence*.) If the
  silent-precedence behaviour should become an error, that is a separate issue
  against `tool-usage`, not part of this plan.
- **`agent` binds to `_matches_agent`** (`cli/tool_usage.py:147-158`, applied
  at `:217-223`), **`tool` binds to `fnmatch.fnmatch`** (`:224-227`) and
  **`server` to `_matches_server`** (`:102-124`, applied at `:228-231`),
  exactly as they do today. Semantics unchanged — including the `--agent`
  any-segment divergence recorded in §7.
- **Asymmetry to preserve:** `agent` filters **both** `tool_uses` **and**
  `availabilities` (`:217-223`), whereas `tool` / `server` filter **only**
  `tool_uses` (`:224-231`) and leave `availabilities` untouched. This is not
  obviously intentional, but Phase 0 must reproduce it verbatim — changing it
  would alter `availability_signal` output under `--tool` / `--server`, which
  the unmodified-tests gate is there to catch.
- The dashboard passes **none** of `agent` / `tool` / `server`.

#### Steps

1. Move the loop body of `cli/tool_usage.py:189-233` into a new
   `collect_per_session(...)` in `src/claude_prospector/tool_collection.py`,
   matching the signature block above exactly.
2. **Session selection stays with the caller; the helper does no time
   filtering and no `--repo` filtering.** This is the load-bearing part of the
   extraction, because session selection is exactly where the two callers
   diverge: `cli/tool_usage.py:193-198` selects on `--repo` plus
   `session.start_time` against `from_date`/`to_date`, whereas the dashboard
   under D-B(a) selects "whatever `aggregate()` already put in
   `result.sessions`". A helper that re-applies date bounds would double-filter
   and silently disagree with `result.total_sessions` — the precise mismatch
   D-B exists to prevent.

   So the signature takes an **already-selected `list[SessionRecord]`** (the
   caller having filtered it) plus the `data_dir` it needs to glob under, and
   the helper owns only: the `projects/*/{session_id}.jsonl` glob, the
   `collect_session()` call, the `OSError` handling, and the `skipped` counter.
   This mirrors
   `compute_tool_usage`, which already pushes selection to its caller by
   contract (`aggregator.py:308-310`).

   The dashboard builds its input by filtering the original `sessions` list
   (`cli/dashboard.py:155`) against
   `{s["session_id"] for s in result.sessions}` — `result.sessions[*]` also
   carries `root_agent` (`aggregator.py:150-158`) if reconstructing from the
   dicts is ever preferable, but filtering the `SessionRecord` list is simpler
   and keeps `collect_session`'s `root_agent` argument
   (`cli/tool_usage.py:212`) coming from the same object it does today.
3. Bind the record-level filters exactly as the signature block specifies:
   keyword-only `agent` / `tool` / `server`, each defaulting to `None`, so the
   dashboard can pass none of them. Keep `_matches_server`
   (`cli/tool_usage.py:102-124`) and `_matches_agent` (`:147-158`) where they
   are or move them alongside, but **do not change their semantics** — and
   preserve the `tool` / `server` `elif` precedence verbatim (see the signature
   block; no new validation).
4. Refactor `cli/tool_usage.py` `run()` to call
   `collect_per_session(selected, args.data_dir, agent=..., tool=...,
   server=...)` — it now does its own `--repo`/date session filtering inline,
   then hands the surviving `SessionRecord`s over.
5. **Under D-J=(a) only — merge the two transcript passes. Separate commit,
   after steps 1-4 are green.** Add to `tool_collection.py`:

   ```python
   def collect_unit(
       unit: AgentTranscript,
   ) -> tuple[list[ToolUseRecord], AgentAvailability]:
       ...
   ```

   One `_iter_entries(unit.jsonl_path)` loop with two branches — the
   `entry["type"] == "assistant"` body from `collect_tool_uses`
   (`tool_collection.py:81-103`) and the `entry["type"] == "attachment"` body
   from `collect_availability` (`:148-169`) — followed by the same post-loop
   normalisation `collect_availability` does today (`:171-187`).
   `collect_session` (`:205-211`) then calls `collect_unit` once per unit
   instead of two visitors. **Keep `collect_tool_uses` and
   `collect_availability` as thin public wrappers over the merged loop** so no
   existing caller or test has to change.

   **Three invariants the merge must preserve — all three are load-bearing and
   all three are silent if broken:**
   - **An `AgentAvailability` is emitted for every unit**, including units with
     no `attachment` entry at all (`signal_present == False`,
     `models.py:177`). `compute_tool_usage` derives `sessions_without_signal`
     and the `sessions_seen_in: null`-vs-`0` distinction from those empty
     records (`aggregator.py:311-319,350-354,391-399`). Dropping them turns
     "unknown" into "zero" and breaks **F6**.
   - **`tool_use.id` de-duplication stays per-file and per-`tool_use.id`
     only** (`tool_collection.py:90-94`) — not per `message.id`. The docstring
     at `:62-66` explains why: parallel tool calls share one `message.id`.
   - **Delta application stays in file order** (`:164-169`): `addedNames` then
     `removedNames`, per entry, in the order entries appear. A merged loop that
     buffers attachments and applies them afterwards changes the result when a
     server is added, removed and re-added.

**Gate (behaviour-preserving refactor, spec N7 precedent at `:483-486`):**

```bash
uv run pytest tests/unit/test_tool_usage.py tests/unit/test_tool_collection.py tests/test_aggregator_tool_usage.py tests/test_cli_subcommands.py
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

`tests/unit/test_tool_usage.py`, `tests/unit/test_tool_collection.py` and
`tests/test_cli_subcommands.py` must all pass **unmodified**. If a test needs
editing to go green, the extraction (step 1-4) or the merge (step 5) changed
behaviour — rework the change, not the test. New cases may be *added* for the
merge (see T13); existing ones may not be edited.

### Phase 1 — flag, aggregation wiring, JSON

**Depends on: D-B, D-C.** (D-G, D-F and D-K are RESOLVED and no longer gate;
build to §4.3's schema.)

1. `AggregateResult`: add `by_mcp_usage: dict[str, dict] = field(default_factory=dict)`
   (`aggregator.py:46-60`, same pattern as `by_skill_adoption` at `:60`).
2. `cli/dashboard.py` `build_parser()`: add `--track-mcp-calls`
   (`action="store_true"`, default `False`) with help text naming the extra
   transcript-read cost.
2b. **Resolve the time bounds once, before `aggregate()`.** Today `run()` hands
   raw argparse values to `aggregate()` and lets it resolve `--window`
   internally (`aggregator.py:94-96`), which is how the `by_skill_adoption`
   denominator bug happened (§ D-C in detail, finding 2). Hoist the resolution:

   ```python
   resolved_from, resolved_to = args.from_date, args.to_date
   if args.window is not None:
       resolved_from = datetime.now(timezone.utc) - timedelta(hours=args.window)
       resolved_to = None
   ```

   Pass `resolved_from` / `resolved_to` to `aggregate()` **and** use them for
   `by_mcp_usage["window"]`. `aggregate()`'s own `window_hours` branch then
   becomes a no-op for this caller (pass `window_hours=None`), so behaviour is
   unchanged — **verify with `tests/test_dashboard_snapshot.py`, which must pass
   unmodified**, and do not delete `aggregate()`'s branch (other callers and
   tests use it).
3. `cli/dashboard.py` `run()`: after the `aggregate()` call (`:158-163`) and
   alongside the skill-adoption block (`:169-179`), add:
   ```
   if args.track_mcp_calls:
       <lazy import of collect_per_session, compute_tool_usage>
       in_window = {s["session_id"] for s in result.sessions}      # D-B(a)
       selected = [s for s in sessions if s.session_id in in_window]
       # data_dir is required — the helper owns the projects/*.jsonl glob.
       # No agent/tool/server filters from the dashboard.
       per_session, skipped = collect_per_session(selected, args.data_dir)
       usage = compute_tool_usage(per_session)          # compact=False; by_agent dropped below
       usage.pop("by_agent", None)                      # D-F(a) RESOLVED — absent, not {}
       usage["warnings"]["unreadable_transcripts"] = skipped
       usage["window"] = {                              # D-K / §4.3
           "start": resolved_from.date().isoformat() if resolved_from else None,
           "end": resolved_to.date().isoformat() if resolved_to else None,
           "sessions": len(per_session),
           "sessions_skipped": skipped,
       }
       result.by_mcp_usage = usage
   ```
   The shape produced here **is** §4.3 — no other code may add or rename keys.

   **Why `by_agent` is popped rather than never built:** `compute_tool_usage`
   has no "skip `by_agent`" option — its only knob is `compact`, which changes
   the *shape* of `by_agent` rather than omitting it (`aggregator.py:303-306,
   325-328`). Popping after the fact is therefore the only way to honour
   D-F=(a) without modifying a shipped aggregator that `tool-usage` depends on.
   Discarding the built dict is deliberate, not an oversight; it costs one
   in-memory dict that is never serialised.
   Follow the existing lazy-import convention (`cli/dashboard.py:172`) so the
   import cost is not paid when the flag is off. **Do not drop `skipped`** —
   it is the panel's own data-quality caveat, and `cli/tool_usage.py:243`
   already establishes `warnings["unreadable_transcripts"]` as its home
   (`compute_tool_usage` itself emits only `malformed_mcp_names`,
   `aggregator.py:422-424`).
4. Surface `by_mcp_usage` per D-C, with **different conditionality on each
   side**:
   - `renderer.py`'s `data` dict (`:87-98`) — **unconditional**. `window.DATA`
     is an internal surface consumed only by the bundled view JS, and the view
     must distinguish "flag off" from "flag on, no MCP calls" anyway (D-E).
   - `cli/dashboard.py`'s `payload` (`:201-213`) — **only when
     `args.track_mcp_calls` is set**. `--format json` is a consumer contract,
     and the spec already settles it: "that field is gated behind
     `dashboard --track-mcp-calls` (default off), so existing JSON consumers
     are unaffected until they opt in"
     (`docs/superpowers/specs/mcp-tool-usage-analyzer.md:699-702`). An
     unconditional `"by_mcp_usage": {}` would violate F8.

   Under **D-C=(b) (recommended)** `by_skill_adoption` is not touched here at
   all — file the follow-up issue instead (see the D-C box for what it must
   say). Under **D-C=(a)** all three parts land as one **separate commit** in
   this PR: payload key, date-bounds fix, reviewed snapshot re-capture.

**Gates:**

- `tests/test_cli_subcommands.py:104-108` — `test_track_mcp_calls_flag_is_rejected`
  asserts `tool-usage --track-mcp-calls` exits non-zero with "unrecognized
  arguments". **This test must still pass unmodified**; the flag lands on
  `dashboard`, not `tool-usage`.
- New mirror test: `dashboard --track-mcp-calls` is *accepted* and
  `args.track_mcp_calls` defaults to `False`. Template:
  `TestToolUsageSubcommand.test_defaults` (`tests/test_cli_subcommands.py:110-119`).
- **`tests/test_dashboard_snapshot.py` must pass unmodified** unless D-C=(a) is
  chosen. This is the gate that catches an accidental unconditional
  `by_mcp_usage` key in `payload` (F8) *and* an accidental behaviour change from
  the step-2b bounds hoist. Under D-C=(a) it is edited **deliberately**, with
  the diff reviewed in the PR body.
- **Perf, per N5 and N6 — record all of it in the PR body:** (i) flag-off
  before/after (N5, expected: no change); (ii) flag-on wall-clock on the full
  local corpus against gates **G1/G2**; (iii) corpus size — session count,
  transcript-file count, total MB — so the placeholder thresholds in N6 can be
  replaced with calibrated ones. **G1's outcome decides D-I** (G3/G4); do not
  defer this measurement to Phase 3.

### Phase 2 — the view

**Depends on: D-H (decide first), then D-D, then D-E. D-F is RESOLVED.**

**Steps 1-8 below are written for D-D=(a) — a new top-level view — because that
is what the recommended D-H=(b) selects.** Rev 2 wrote this phase for D-D=(b)
and Rev 3 inverted it: documenting the non-recommended surface as primary is the
same defect as the Rev 2 `ctx` justification it also fixes — prose pointing one
way while the decision points another. **If D-H=(a) is chosen instead, the
D-D=(b) block after step 8 becomes the body and steps 1-3 drop away.**

1. New file `src/claude_prospector/static/views/mcp-usage.js`, exposing
   `window.renderMcpUsage(root)` in the shape the sibling views use
   (`static/views/economics.js`, `static/views/layout-b-diag.js:977`).
2. Wire the four shell touchpoints, **in this order**:
   - `_read_static("views/mcp-usage.js")` kwarg in `render()`
     (`renderer.py:104-109`) and a matching `{{ ... }}` slot in the template;
   - `<script>` tag (`templates/dashboard.html:293-296`);
   - `.view-toggle` button with `data-view="mcp"` (`:306-317`);
   - `_VIEW_SUBS` entry (`:330-338`).
3. **The `_renderView` branch — read the trap box before writing it.**
   `templates/dashboard.html:340-357`.

   > **Trap — `_renderView` ordering.** The final `else` in `_renderView`
   > (~`templates/dashboard.html:353`) is a **catch-all that calls
   > `renderEconomics`**, not an explicit `else if (view === 'advanced')`
   > guard. The new `else if (view === 'mcp')` branch **must be inserted
   > BEFORE that catch-all, not after.** Two failure modes it prevents:
   > appending the branch after the catch-all makes it unreachable, and
   > shipping the `data-view="mcp"` button without the branch at all makes the
   > new tab silently render the **Economics** view — no console error, no
   > visual cue that anything is wrong. Both failures survive every automated
   > gate in this repo (§ What CAN and CANNOT be tested), so this is one of the
   > things the blocking manual check must look at.

4. **Data access — read `window.DATA.by_mcp_usage || {}` directly.** A
   top-level view has no `ctx`; it reads the payload itself, exactly as
   `economics.js` and `layout-b-diag.js` do. Per the correction in the D-D=(b)
   block below, direct access **is** this file family's convention for raw
   server-side dicts, so nothing is anomalous here.
5. Empty state per D-E (flag off ⇒ `by_mcp_usage` is `{}`), with copy that
   depends on **D-I** — see that row; do not write copy naming only the CLI
   flag before D-I is settled.
6. Unreadable-transcript banner per **F9** — rendered when
   `by_mcp_usage.warnings.unreadable_transcripts > 0`, above the counts, and
   independent of the D-E empty state. (One key, two layers: Phase 1 writes
   `usage["warnings"]["unreadable_transcripts"]` in Python; it arrives as
   `window.DATA.by_mcp_usage.warnings.unreadable_transcripts`.)
7. Render the `sessions_seen_in: null` case distinctly from `0` (**F6**), and
   use `CP.PALETTE` / `CP.fmtTokens` / `CP.applyChartDefaults()` from
   `cp-utils.js` rather than re-declaring helpers — that module is the only
   genuinely shared one across the view files.
8. **Time-basis line per F10**, read from `by_mcp_usage.window`. On the
   D-D=(a) path there is no period selector in scope, so the line states the
   time basis only ("all time" when `window.start`/`window.end` are both
   `null`, which is the default and the hook's path).

**If D-D=(b) is chosen instead** (i.e. D-H=(a)), the panel is a fifth row in
`TAB_DEFS` (`static/views/layout-b-diag.js:881-886`) plus a `build` function,
`templates/dashboard.html` and `renderer.py`'s `_read_static` calls are
untouched, and two things change:

- **F10's line must additionally say the panel does not respond to the period
  buttons** — not optional, same standing as D-B=(a)'s "whole-session counts"
  label (§2.6).
- **Calling convention becomes `ctx` — with the Rev 2 justification
  withdrawn.** Rev 2 justified `ctx` by claiming direct `window.DATA` access
  "would make this the only tab in the registry with a different data-access
  path". That claim is **wrong about the file's actual convention** and is
  withdrawn. Verified: the `ctx` builder is `compute()` at
  `static/views/layout-b-diag.js:988-1001` (Rev 2's `unverified:` marker is
  resolved — it sits inside `window.renderLayoutBDiag` and produces every `ctx`
  key). Everything it memoises is **derived** (`CP.filterSessions`,
  `CP.reAggregate`, `computeBurnRates`, `computeTopSessions`, `computeMovers`,
  `computeEfficiency`), and the functions producing those derived values read
  `window.DATA` **directly** — `computeMovers()` at `:490-497` reads
  `window.DATA.sessions` and `window.DATA.by_agent` with no `ctx` at all, and
  it feeds `ctx.movers`, which feeds `tabMovers` in the very same `TAB_DEFS`
  registry. `secondary()` (`:1033-1044`) likewise reads
  `window.DATA.by_skill_adoption` directly — the closest existing analogue to
  this panel, being another server-side pre-aggregated dict.

  **The real convention is: derived values are memoised into `ctx`; raw
  server-side dicts are read directly at the point of use.** `ctx` is still the
  right choice *on this path*, for two mechanical reasons that survive the
  correction: `tagFor(id, ctx)` (`:888-915`) renders a tab's badge and receives
  **only** `ctx`, so a future "3 dormant servers" badge has no other channel;
  and the `|| {}` normalisation the D-E empty state needs then lives in exactly
  one place instead of being repeated in the build function and again in
  `tagFor`. So `compute()` (`:994-1000`) gains one line —
  `mcpUsage: window.DATA.by_mcp_usage || {}` — and the build function reads
  `ctx.mcpUsage`. A deliberate, narrow departure from the raw-dict convention,
  taken for those two reasons, **not** because direct access would be
  anomalous. It would not be.

**Packaging note:** `pyproject.toml:25` already globs
`claude_prospector = ["templates/*.html", "static/**/*"]`, so a new file under
`static/views/` ships without a `pyproject.toml` edit. Verify anyway, per
CLAUDE.md § CI gates:

```bash
uv build --wheel
unzip -l dist/claude_prospector-*.whl | grep static/views
```

**Gates:**

- `tests/test_phase2_shell.py` — **re-verified in Rev 3, because D-D=(a) adds a
  `.view-toggle` button and this test would be the first to break if it were
  strict.** It is not: `test_view_toggle_element_present` (`:213-218`),
  `test_view_container_present` (`:220-225`) and
  `test_data_view_attributes_present` (`:227-232`) are plain `in html`
  substring assertions, and the tab tests (`:199-211`) each assert one label
  string. Nothing counts buttons or asserts a fixed list, so a fifth
  `data-view` is genuinely additive. **Stays gate-only — run unmodified, do
  not edit.**
- `tests/test_phase3_views.py` asserts each view JS file resolves via
  `importlib.resources`; add an equivalent assertion for any new file.
- Full suite + both lint commands.

#### What CAN and CANNOT be tested automatically — read before writing T9/T12

**Verified: this repo has no JavaScript execution capability of any kind.**
There is no `package.json` anywhere in the tree (glob `**/package.json` → no
matches), and the dev dependency group is exactly `ruff~=0.6.0` and
`pytest~=8.0` (`pyproject.toml:14-18`). No jsdom, no playwright, no node in CI.
Every existing JS-adjacent test asserts on **source text or resource
resolution**, never on rendered DOM.

Three options were considered; **option (b) is chosen**:

- **(a) Introduce a JS test runner.** Rejected. Note the precise reason: N1
  says "no new **runtime** dependency", and a dev-only harness would not
  strictly violate it — so N1 is *not* the objection. The objection is that
  adding a Node toolchain to CI on **both** Ubuntu and Windows (CLAUDE.md § CI
  gates runs Test and Skill Smoke on both) to gate two assertions is out of
  proportion to this feature, and it would need its own issue, its own CI
  matrix change, and a `wheel-smoke` interaction review.
- **(b) Downgrade T9/T12 to source-containment assertions, and verify the
  rendered behaviour manually with a scripted, reproducible procedure.**
  **Chosen.**
- **(c) Ship F6/F9 unverified.** Rejected — F6 is the distinction the panel
  exists to show (spec §2.3, `:171-194`), and an untested `null`-vs-`0` bug is
  invisible in review precisely because both render as *something*.

**Consequence, stated plainly: F6 and F9 are NOT covered by an automated test
in this plan.** T9 and T12 gate that the handling *code exists*; they cannot
gate that it *renders correctly*. The manual step below is the only thing that
does, and it is a **required, blocking Phase 2 gate**, not a suggestion.

**Manual render verification — Phase 2 exit gate (blocking, record the result
in the PR body):**

1. Build a fixture dashboard from a hand-written payload in which
   `by_mcp_usage.by_server` contains one server with
   `"sessions_seen_in": null` and one with `"sessions_seen_in": 0`, and
   `by_mcp_usage.warnings.unreadable_transcripts` is `2`.
2. Generate the HTML (`uv run python -m claude_prospector dashboard ...` against
   that fixture data dir, or by rendering with the fixture injected) and open it
   in a browser.
3. Confirm, and state each in the PR body: (i) the `null` server renders as
   "unknown"/"—" and the `0` server renders as `0`, **visibly differently**;
   (ii) the skipped-sessions banner appears with the count `2`; (iii) with
   `unreadable_transcripts` set to `0`, the banner is absent; (iv) the F10
   time-basis line matches the fixture's `window` block.
4. Attach a screenshot or quote the rendered text. "Checked manually" without
   the observed output does not satisfy this gate.

### Phase 3 — hook reconciliation, documentation, durable decision capture

**Depends on: D-I, and on N6's G1 measurement from Phase 1.**

0. **Resolve the Stop-hook path (D-I).**
   - Under **D-I=(a) (recommended for v1)**: no code change to
     `hooks/dashboard-regen.py` or `hooks/hooks.json`. Instead — (i) confirm
     D-E's empty-state copy names the limitation (the hook does not collect
     this data; run the CLI flag by hand), (ii) add a README line saying the
     automatic session-end regeneration does **not** populate the MCP panel,
     and (iii) **file the D-I=(b) follow-up issue** with the G1 number from
     Phase 1 quoted in it, so the toggle can be scoped against a real cost.
   - Under **D-I=(b)**: add `track_mcp_calls` to `userConfig`
     (`.claude-plugin/plugin.json:13-20`, mirroring `autoregen` exactly);
     add `"--track-mcp", "${user_config.track_mcp_calls}"` to the Stop hook's
     `args` array (`hooks/hooks.json:24-38`); parse it in the hook with the
     existing `_parse_autoregen_arg` helper (`hooks/dashboard-regen.py:162-179`
     — it already treats the empty-string substitution as falsy, which is the
     never-configured case); and append `--track-mcp-calls` to the subprocess
     argv (`:581-594`) only when truthy. Extend
     `tests/test_dashboard_regen_hook.py` with both branches: flag absent from
     argv when the toggle is off, present when on. **Blocked unless N6's G1
     came in under 45 s** (G3).
   - **D-I=(c) is rejected** — see the D-I row.
1. README: document `dashboard --track-mcp-calls` in the dashboard section,
   including the extra transcript-read cost and (per D-I) whether the
   session-end hook can produce the panel's data.
2. Update the spec status line
   (`docs/superpowers/specs/mcp-tool-usage-analyzer.md:26-29`) — "§8 Phase 3
   remains open under #248" becomes closed, and §8 Phase 3 (`:694-702`) is
   reconciled with what actually shipped (notably the D-D outcome, since the
   spec sketch assumes a new top-level tab).
3. **Post the resolved §3 decisions as a comment on issue #248** before this
   plan file is deleted. Per CLAUDE.md § Lifecycle, this file is removed when
   #248 closes; the decision rationale must land somewhere durable first.
   Attribution line required per CLAUDE.md § GitHub Comments.

**Closeout gate — must complete before this plan file is deleted:**

4. **File GitHub issues for the follow-ups listed in §7, and record their
   issue numbers in the closing comment on #248.** Rev 3 raises the count from
   three to five:
   1. The `--agent` leaf-vs-any-segment semantics divergence
      (`cli/tool_usage.py:147-158` vs spec F3 `:371-382`).
   2. D7 — token cost per MCP call, deferred by the repo owner on 2026-08-22.
   3. **Corrected in Rev 5.** The `subagents/workflows/wf_*/` parser gap is
      almost certainly already resolved: issue **#253**, closed by PR **#255**
      (`83010fe`, merged 2026-08-22), matches this item's scope and description
      exactly. Phase 3 must **confirm #253 is the sibling issue referenced by
      spec §10** (`gh issue view 253` or reading the issue is enough) and, if
      confirmed, **this closeout item is already satisfied — no new issue
      needs filing.** Record #253 (not a new issue number) in the closing
      comment on #248. If #253 turns out **not** to match spec §10's sibling
      issue, the original instruction still applies as a fallback: check
      whether spec §10 (`:739-742`)'s sibling issue was filed under a
      different number, and file it only if it was not.
   4. **(Rev 3, under D-C=(b) — the recommendation)** `by_skill_adoption` is
      absent from `dashboard --format json`'s `payload`
      (`cli/dashboard.py:201-213`) while present in the HTML `data`
      (`renderer.py:94`), **and** it is computed from raw `args.from_date` /
      `args.to_date` rather than window-resolved bounds
      (`cli/dashboard.py:174-179` vs `aggregator.py:94-96`), so a
      `--window`-scoped run reports all-time adoption. The issue must say both
      halves and must warn that adding the payload key alone ships a wrong
      number, and that either change re-captures
      `tests/fixtures/dashboard_snapshot_pre_refactor.json`.
   5. **(Rev 3, under D-I=(a) — the recommendation)** Add a
      `track_mcp_calls` plugin `userConfig` toggle so the session-end Stop hook
      can produce the MCP panel's data. Quote the N6/G1 measurement in the
      issue body; the toggle is only worth building if the flag-on run fits
      well inside the hook's 120 s timeout.

   Rationale: §7 records all of them as **unfiled**, and CLAUDE.md § Document
   Files (Lifecycle) deletes this plan when #248 closes. Without durable issue
   numbers these evaporate with the file. "Extract durable info before
   deletion" is the lifecycle rule this gate implements. Deleting the plan with
   any of the three still unfiled is a closeout failure, not a judgement call.

---

## 6. Test plan

| # | Test | Asserts |
| --- | --- | --- |
| T1 | Phase 0 parity | `tests/unit/test_tool_usage.py` + `tests/test_cli_subcommands.py` pass **unmodified** after the helper extraction |
| T2 | Flag default | `dashboard` parses with `track_mcp_calls is False` when the flag is absent |
| T3 | Flag accepted | `dashboard --track-mcp-calls` parses without error |
| T4 | Inverse gate | `tool-usage --track-mcp-calls` still rejected (`tests/test_cli_subcommands.py:104-108`, unmodified) |
| T5 | Off ⇒ no collection | With the flag off, `collect_per_session` is not called and `result.by_mcp_usage == {}`. **Patch target: `claude_prospector.tool_collection.collect_per_session`** — see the note below the table before writing this test. |
| T6 | JSON payload gating | `--format json --track-mcp-calls` emits `by_mcp_usage`; **`--format json` without the flag omits the key entirely** (Phase 1 step 4 — protects F8's byte-identical guarantee for existing consumers) |
| T7 | `by_skill_adoption` payload fix | Only if D-C=(a): `--format json` emits `by_skill_adoption` **with window-resolved bounds** (assert a `--window`-scoped run differs from an all-time run), and the snapshot fixture is updated deliberately |
| T8 | Renderer data key | `render()` output contains `by_mcp_usage` inside `window.DATA` |
| T9 | Null-vs-zero handling **exists** (F6) | **Reworded in Rev 3 — source containment, not rendering.** Assert the view source distinguishes the cases, e.g. `=== null` / `== null` appears in the `sessions_seen_in` branch and the literal fallback string ("unknown"/"—") is present. **This does NOT prove correct rendering** — that is the blocking manual gate in Phase 2. Label F6 in the PR body as *verified manually, not by automated test*. |
| T10 | Session-scope denominator | Only if D-B=(a): the session set fed to `compute_tool_usage` equals `{s["session_id"] for s in result.sessions}`, and `by_mcp_usage["window"]["sessions"] == result.total_sessions` |
| T11 | View resource | The new/edited view JS resolves via `importlib.resources` and appears in the built wheel |
| T12 | Skipped-sessions banner handling **exists** (F9) | **Reworded in Rev 3 — source containment, not rendering.** Assert `"unreadable_transcripts"` appears in the view JS source and is guarded by a `> 0` comparison. **Does NOT prove the banner renders** — Phase 2's manual gate does. Label F9 in the PR body as *verified manually, not by automated test*. |
| T13 | Merged-pass parity (D-J=(a)) | `tests/unit/test_tool_collection.py` passes **unmodified**, plus a new case: a session where one agent transcript contains **no** `attachment` entry still yields an `AgentAvailability` with `signal_present is False`, and `compute_tool_usage` over it still produces `sessions_seen_in: None` rather than `0` (the §2.5 trap) |
| T14 | Resolved bounds (Phase 1 step 2b) | `dashboard --window 7d --track-mcp-calls --format json` emits `by_mcp_usage.window.start` as a **date, not `null`**; a run with no time flags emits `null`/`null`. Guards the D-C finding-2 bug class from recurring on the new field. |
| T15 | Payload shape (D-K / §4.3) | `by_mcp_usage` contains exactly `by_tool`, `by_server`, `availability_signal`, `warnings`, `window` — **`by_agent` and `compact` are absent**, not empty |

**T5 — patch target, and why it is the source module.** `unittest.mock.patch`
replaces a name *where it is looked up*. Phase 1 step 3 uses a **function-local
import** inside the `if args.track_mcp_calls:` body, mirroring the existing
lazy-import convention at `cli/dashboard.py:172`
(`from claude_prospector.aggregator import compute_skill_adoption`). Under a
function-local import, `claude_prospector.cli.dashboard` **never binds
`collect_per_session` as a module attribute**, so
`patch("claude_prospector.cli.dashboard.collect_per_session")` raises
`AttributeError` at patch *setup* — it fails whether or not the function is
ever called. The lookup site is the source module, resolved at call time:

```python
with patch("claude_prospector.tool_collection.collect_per_session") as spy:
    ...
    spy.assert_not_called()
```

**Coupling note:** this target is correct *because* the import is
function-local. If Phase 1 step 3 is ever promoted to a module-level import in
`cli/dashboard.py`, the patch target must move to
`claude_prospector.cli.dashboard.collect_per_session`. Do not promote the
import merely to simplify the test — the lazy import is what keeps the import
cost off the flag-off path (D-G, N5).

---

## 7. Out of scope

> **Five follow-ups below are UNFILED as of 2026-08-22.** No GitHub write tool
> was used in any session that produced or revised this plan. Per CLAUDE.md
> § Document Files (Lifecycle) this file is deleted when #248 closes, so these
> evaporate unless issues exist: (1) the `--agent` leaf-vs-any-segment
> divergence, (2) D7 token cost per MCP call, (3) confirmation that the
> `workflows/wf_*/` sibling issue from spec §10 was actually filed —
> **corrected in Rev 5**: this is issue **#253**, closed by PR **#255**
> (`83010fe`, merged 2026-08-22), so almost certainly already satisfied; see
> Phase 3 step 4 for the confirmation step,
> (4) **Rev 3** — the `by_skill_adoption` payload omission **and** its
> wrong-date-bounds bug (under D-C=(b)), (5) **Rev 3** — the
> `track_mcp_calls` userConfig/Stop-hook toggle (under D-I=(a)).
>
> **Filing these is a hard closeout gate — see Phase 3 step 4.** The plan may
> not be deleted until all of them have issue numbers recorded on #248.

- **Token cost per MCP call (D7).** Explicitly deferred by the repo owner's
  2026-08-22 comment on #248 and by spec D7
  (`docs/superpowers/specs/mcp-tool-usage-analyzer.md:508`). File a follow-up if
  still wanted after the panel ships.
- **Fixing the `subagents/workflows/wf_*/` parser gap.** **Corrected in
  Rev 5** — not outstanding out-of-scope work: PR #255 / issue #253
  (`83010fe`, merged 2026-08-22) closed this gap before this plan's Phase 2
  work began. Retained here for the historical record only; see the Rev 5
  note above and §2.3 for the full correction.
- **Adding `timestamp` to `ToolUseRecord`.** Only in play if D-B=(b) is chosen
  over the recommendation.
- **A skill front-end for MCP usage.** Spec §10 (`:753-761`) deferred this
  pending a settled JSON shape and a shipped dashboard panel; revisit after.
  §4.3 now settles the shape, which removes half of that blocker.
- **Fusing tool collection into `parse_sessions`' walk.** Evaluated and
  rejected in Rev 3 with reasons (§2.5). Not a follow-up — a decision. If it is
  ever revisited, the blocking question is how `tool-usage`'s
  filter-between-parse-and-collect ordering survives.
- **Making `render()` write atomically** (`renderer.py:125`). A truncated
  dashboard after a hook timeout (§2.7) is a pre-existing defect, not one this
  panel introduces; N6's ceiling is the mitigation here. Worth its own issue if
  the hook path ever gets closer to the 120 s limit.
- **A JS test runner for the view files.** Rejected for this feature with
  reasons (Phase 2 § What CAN and CANNOT be tested). If the view layer grows
  enough to justify it, that is its own issue with its own CI-matrix change.
- **`--agent` semantics reconciliation.** `_matches_agent`
  (`cli/tool_usage.py:147-158`) matches **any** segment of the agent path
  (`wanted in agent_path`), while spec F3 (`:371-382`) specifies **leaf-name**
  matching. This is a pre-existing divergence in shipped code, not introduced
  here. Phase 0 must preserve it verbatim; **file a separate issue** so it is
  resolved deliberately rather than silently during a refactor.

---

## 8. Sources

**Repo, verified by read on 2026-08-22 at `main` @ `3b6ae6d`:**
`src/claude_prospector/aggregator.py:1-80,77-136,144-203,296-425`;
`src/claude_prospector/cli/dashboard.py:1-225`;
`src/claude_prospector/cli/tool_usage.py:1-246`;
`src/claude_prospector/renderer.py:1-131`;
`src/claude_prospector/models.py:1-185`;
`src/claude_prospector/templates/dashboard.html:280-379`;
`src/claude_prospector/static/views/layout-b-diag.js:881-885,977-1051`;
`tests/test_cli_subcommands.py:95-119`;
`tests/test_phase2_shell.py:214-232`; `tests/test_phase3_views.py:55-129`;
`tests/test_aggregator_tool_usage.py:212-217`;
`pyproject.toml:21-28`;
`docs/superpowers/specs/mcp-tool-usage-analyzer.md` (full read);
`CLAUDE.md` § CI gates, § Repo layout, § Branch / worktree conventions;
`~/.claude/CLAUDE.md` § Document Files (Lifecycle), § GitHub Comments.

**Rev 2 additions, verified by read on 2026-08-22 at `main` @ `3b6ae6d`:**
`src/claude_prospector/cli/dashboard.py:140-225` — confirms the function-local
import at `:172` (`from claude_prospector.aggregator import
compute_skill_adoption`) that determines T5's patch target, and that
`args.data_dir` is available in `run()` (`:154-155`).
`src/claude_prospector/cli/tool_usage.py:205-239` — confirms the `if args.tool
… elif args.server` precedence at `:224-231` and the agent-vs-tool/server
filter asymmetry. Repo-wide grep for `patch(` in `tests/` confirms no existing
test patches `parse_skill_tracking` or `compute_skill_adoption`, so there is no
in-repo precedent for the lazy-import patch target — T5 establishes it.

**Rev 3 additions, verified by read on 2026-08-22 at `main` @ `3b6ae6d`:**
`src/claude_prospector/parser.py:316-373,379-465,468-521` — the `walk_session`
call is at **`:440`**, not `:506` as the Rev 3 review brief stated (`:506` is
the `project_dir.glob("*.jsonl")` line in `parse_sessions`); confirms
`_parse_jsonl_messages` opens each transcript once per unit.
`src/claude_prospector/transcript_walker.py:1-12,71-114` — the two-visitor
design statement and the walk's cost profile.
`src/claude_prospector/tool_collection.py:30-55,57-103,125-187,190-211` —
confirms `collect_tool_uses` and `collect_availability` each call
`_iter_entries` independently (the third read, §2.5) and that
`collect_session` appends one `AgentAvailability` per unit unconditionally.
`src/claude_prospector/aggregator.py:94-96` (window→`from_date` resolution,
the D-C finding-2 root cause), `:303-425` (`compute_tool_usage` return keys,
§4.3).
`src/claude_prospector/cli/dashboard.py:83-99` (`--from`/`--to`/`--window` all
default `None`), `:169-179` (raw-args skill-adoption call), `:200-215`
(`payload` key set).
`src/claude_prospector/cli/tool_usage.py:160-246` — stdout shape
(`compute_tool_usage` + `window` + `compact` + `unreadable_transcripts`), the
source of §4.3's "not identical to `tool-usage`" finding.
`src/claude_prospector/renderer.py:87-98,112-130` — `data` dict contents and
the **non-atomic** `write_text` at `:125`.
`src/claude_prospector/static/views/layout-b-diag.js:437-477,490-531,881-886,
977-1001,1003-1009,1011-1031,1033-1044,1122-1128,1177` — `compute()` is the
`ctx` builder (resolves Rev 2's `unverified:` marker); `computeMovers()` and
`secondary()` read `window.DATA` directly; `state.period` defaults to `'7d'`;
the header renders "this ${state.period}"; the period buttons re-render.
`hooks/dashboard-regen.py:472-614` (autoregen gate, version check, the
`timeout=120` subprocess, and the fact that only a non-zero **exit code**
writes the failure page — `TimeoutExpired` falls to the outer handler at
`:607`); `hooks/hooks.json:24-38`; `.claude-plugin/plugin.json:13-20`
(`userConfig.autoregen`, the precedent for D-I=(b)).
`tests/test_dashboard_snapshot.py:32-80` and
`tests/fixtures/dashboard_snapshot_pre_refactor.json` (11 top-level keys, no
`by_skill_adoption`); fixture tree is a single JSONL file at
`tests/fixtures/session_summaries/dashboard_baseline_input/projects/fake-project-abc123/session-001.jsonl`.
`tests/test_phase2_shell.py:199-232` — all substring `in html` assertions, no
button counting and no fixed-list assertion, which is what makes a fifth
`data-view` additive under D-D=(a) (re-verified in Rev 3 rather than assumed).
`pyproject.toml:14-18` (dev deps = `ruff` + `pytest` only); glob
`**/package.json` over the whole repo → **no matches** (Charge 4 confirmed).
`tests/unit/test_tool_collection.py` and `tests/test_dashboard_regen_hook.py`
exist and are the regression harnesses for D-J and D-I respectively.

> **Measurement gap, Rev 3.** No shell tool was available in the revising
> session, so **nothing in this plan was timed or sized**. Every number in N6
> is a placeholder with a stated rationale, to be replaced by the executor at
> the end of Phase 1. Treat them as thresholds to test against, not as
> observations.

**Git:** `git log` at session start — `3b6ae6d` ("collect tool invocations and
MCP availability from transcripts (#251)"), `dd7c250` (#250), `812cd16` (#249).

**GitHub:** issue #248 body and its 2026-08-22 repo-owner comment, both supplied
verbatim in the dispatch brief rather than fetched via the API in this session —
`unverified:` live issue state (open/closed, labels, milestone) was **not**
independently confirmed. Confirm before relying on it for closing keywords.
Issue #195 and PR #252 are cited only via the spec's own implementation-history
line (`docs/superpowers/specs/mcp-tool-usage-analyzer.md:31-33`), which is
in-repo and verified.
