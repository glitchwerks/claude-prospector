---
title: Deep per-session effort and activity analytics
issue: 310
status: approved
touches:
  - src/claude_prospector/models.py
  - src/claude_prospector/parser.py
  - src/claude_prospector/transcript_walker.py
  - src/claude_prospector/tool_collection.py
  - src/claude_prospector/aggregator.py
  - src/claude_prospector/cli/dashboard.py
  - src/claude_prospector/renderer.py
  - src/claude_prospector/static/cp-utils.js
  - src/claude_prospector/static/views/session-detail.js
  - src/claude_prospector/templates/dashboard.html
  - .github/workflows/ci.yml
  - tests/
  - README.md
skills_relevant:
  - python
  - frontend-design
  - github-actions
---

# Deep per-session effort and activity analytics

Tracking: issue #310. The requirements and interaction decisions in this
document are the approved acceptance criteria recorded in #310. Repository
citations were verified at commit `be75a23` on 2026-09-13.

## 1. Outcome

Add a dedicated session page to the existing self-contained dashboard. The
page explains how recorded token usage accumulated across one root session and
all of its discovered subagents. It combines:

- a whole-session, adaptively bucketed token overview split by recorded effort;
- a scoped detail view that uses the whole session in `All`, the selected range
  in `By time period`, and exact per-response bars when the viewport can render
  them legibly;
- separate activity tracks for every root-to-leaf agent path;
- exact response, effort, model, agent, and token-component totals;
- compact, expandable summaries of agent hierarchy, actual skill invocations,
  recognized commands, session facts, and opt-in MCP calls; and
- one chronological ledger of the deterministic events included by the current
  filters.

The page is descriptive, not interpretive. It does not infer why an effort or
model changed, whether the session stayed on task, what work was completed, or
whether a choice was good. This boundary is required by #310.

## 2. Existing seams and constraints

The design extends existing contracts instead of introducing a second session
analytics pipeline:

1. `MessageRecord` already stores timestamp, full model ID, full agent path,
   skill, and all four token components
   (`src/claude_prospector/models.py:L9-L47`). `effort` is the missing response
   dimension. A committed transcript fixture proves that effort is available as
   a top-level assistant-entry field and may repeat across fragments
   (`tests/fixtures/duplicate_message_id.jsonl:L2-L4`).
2. The parser already deduplicates token snapshots by `message.id`, merges a
   later Skill block into the retained response, and avoids summing repeated
   usage snapshots (`src/claude_prospector/parser.py:L361-L445`). This remains
   the source of truth for what counts as one response.
3. `aggregate()` already filters at message timestamp granularity and emits a
   timestamped `agent_activity` record for every retained message
   (`src/claude_prospector/aggregator.py:L160-L201`,
   `src/claude_prospector/aggregator.py:L251-L276`). The record currently lacks
   effort, full model, input tokens, and output tokens
   (`src/claude_prospector/aggregator.py:L80-L96`).
4. The shared transcript walker already yields the root first and recursively
   discovers ordinary and workflow subagents while retaining a full
   root-to-leaf `agent_path` (`src/claude_prospector/transcript_walker.py:L71-L114`,
   `src/claude_prospector/transcript_walker.py:L236-L341`). Its existing
   ten-segment safety cap remains unchanged
   (`src/claude_prospector/transcript_walker.py:L26-L27`,
   `src/claude_prospector/transcript_walker.py:L294-L305`).
5. Tool collection already deduplicates calls by `tool_use.id`, specifically
   because multiple transcript fragments may share a message ID while carrying
   distinct tool calls (`src/claude_prospector/tool_collection.py:L161-L192`,
   `src/claude_prospector/tool_collection.py:L212-L241`). The collected record
   has agent attribution and optional result size but no timestamp
   (`src/claude_prospector/models.py:L151-L184`).
6. MCP collection already returns records grouped by session before
   `compute_tool_usage()` collapses them into global totals
   (`src/claude_prospector/tool_collection.py:L413-L492`,
   `src/claude_prospector/cli/dashboard.py:L218-L243`). The session page can
   retain an additive projection of these existing records when collection is
   enabled.
7. The generated report already embeds one escaped JSON payload and inlines all
   JavaScript for offline use (`src/claude_prospector/renderer.py:L81-L129`,
   `src/claude_prospector/templates/dashboard.html:L284-L302`). New session
   data and view code follow that pattern. Package data already includes every
   file under `static/**/*` (`pyproject.toml:L24-L25`).
8. The current shell always renders the Overview view at startup and its tabs
   do not update browser history (`src/claude_prospector/templates/dashboard.html:L363-L427`).
   Session navigation therefore requires a small router rather than another
   top-level tab.

## 3. Data design

### 3.1 Response records

`MessageRecord` gains `effort: str | None`. The parser reads only the top-level
assistant entry's `effort` field. A non-empty string becomes the recorded effort
label after whitespace trimming. Missing, blank, and non-string values become
`None`; the UI labels that bucket `Unknown`. The payload also includes a
case-normalized `effort_key` for grouping. Unknown but well-formed future
strings remain their own labeled bucket instead of being coerced to `Unknown`.
This preserves the observed value while remaining forward-compatible (#310).

When duplicate fragments share a message ID, the retained response keeps one
usage snapshot. If the retained fragment has no effort and a later fragment has
a valid effort, the parser fills the missing value. Conflicting non-null effort
values for the same message ID are not averaged or selected by rank: the first
recorded value remains authoritative and a deterministic conflict count is
added to parser diagnostics. This matches the current first-response
deduplication rule rather than inventing a session-level interpretation
(`src/claude_prospector/parser.py:L420-L429`; #310).

The existing per-session `agent_activity` array becomes the canonical exact
response payload. Existing keys remain unchanged and the following keys are
additive:

```json
{
  "timestamp": "2026-09-13T12:34:56.789+00:00",
  "agent": "root→code-writer",
  "agent_path": ["root", "code-writer"],
  "model": "sonnet",
  "model_full": "claude-sonnet-5",
  "effort": "high",
  "effort_key": "high",
  "input_tokens": 12,
  "output_tokens": 345,
  "cache_read_tokens": 900,
  "cache_creation_tokens": 40,
  "total_tokens": 1297
}
```

`agent` remains the existing path key so older clients continue to work.
`agent_path` avoids reparsing a display string in the new tree. The payload
contains no message text, thinking, prompt, tool input, or result content.

### 3.2 Actual skill invocations

The current `_extract_skill()` stops at the first matching Skill block
(`src/claude_prospector/parser.py:L319-L328`). The new parser path records every
actual `Skill` tool-use block with:

```json
{
  "timestamp": "2026-09-13T12:35:02.000+00:00",
  "agent": "root→code-writer",
  "agent_path": ["root", "code-writer"],
  "skill": "python"
}
```

Internally, Skill blocks are deduplicated by non-empty tool-use ID. Blocks
without an ID use `(transcript unit, message ID, block index, skill name)` when
a message ID exists, or `(transcript unit, entry UUID, block index, skill name)`
otherwise. This is separate from response deduplication because one repeated
assistant message can expose distinct tool calls (#310;
`src/claude_prospector/tool_collection.py:L173-L192`).

The existing single `MessageRecord.skill` field remains populated with the
first actual invocation for backward-compatible `by_skill` aggregation
(`src/claude_prospector/aggregator.py:L308-L314`). A new per-session
`skill_activity` array supplies the complete invocation list to the session
page. Skills merely passed in an Agent prompt or listed in configuration are
not included (#310).

### 3.3 Commands

The existing `CommandInvocationRecord` is already limited to recognized
external-user wrappers and stores only name and timestamp
(`src/claude_prospector/models.py:L72-L82`,
`src/claude_prospector/parser.py:L331-L358`). Commands continue to be collected
only from the root transcript (`src/claude_prospector/parser.py:L361-L379`).
The session summary exposes them as `command_activity`; no argument or
surrounding prompt text is added.

### 3.4 Session facts

Each session summary adds mechanically derived facts:

- `end_time`, computed from the maximum included response timestamp;
- exact duration between `start_time` and `end_time` in seconds;
- response count, token totals, session ID, project/path, root agent, and all
  observed agent paths; and
- distinct non-empty values observed for `gitBranch`, `entrypoint`, and
  transcript `version`, ordered by first observation.

For the last three fields the parser retains observed values, not a selected
"primary" value. If a value changes, the expanded facts panel lists every
distinct value with its first-seen timestamp and agent paths. Missing fields
render as `Not recorded`. This avoids turning concurrent or changing metadata
into an unsupported scalar (#310). `SessionRecord` already supplies the base
identity, project path, root agent, messages, descendants, and commands
(`src/claude_prospector/models.py:L85-L129`).

### 3.5 MCP activity and collection state

`ToolUseRecord` gains a timestamp copied from the assistant transcript entry.
When either MCP flag triggers the existing collection pass, the dashboard
retains a per-session projection containing only calls whose names normalize as
MCP tools:

```json
{
  "timestamp": "2026-09-13T12:36:10.000+00:00",
  "agent": "root→researcher",
  "agent_path": ["root", "researcher"],
  "server": "github",
  "method": "get_issue",
  "call_count": 1,
  "result_chars": null,
  "result_excluded": false
}
```

Individual records use `call_count: 1`; the client may group identical rows
for compact summaries while the expanded ledger remains chronological. Server
and method use the same normalizer as the global MCP report. Malformed MCP
names remain in diagnostics and are not silently reclassified (#310).

Every session carries explicit collection state:

```json
{
  "mcp_collection": {
    "calls": "not_collected",
    "result_sizes": "not_collected"
  },
  "mcp_activity": null
}
```

When call collection ran successfully, `calls` is `collected` and
`mcp_activity` is an array, where an empty array means exactly zero recorded
calls. When collection was requested but the transcript was unreadable,
`calls` is `unavailable` with a machine-readable warning. Result sizes have an
independent state because `--track-mcp-call-sizes` is a separate privacy opt-in
(`src/claude_prospector/cli/dashboard.py:L139-L163`). A null result size never
means zero; the existing measured-zero versus unavailable distinction remains
intact (`src/claude_prospector/models.py:L163-L176`).

### 3.6 Additive compatibility

No existing aggregate or session key is removed or redefined. HTML and JSON
outputs receive the same additive session fields. `by_mcp_usage` remains gated
in JSON mode as it is today (`src/claude_prospector/cli/dashboard.py:L264-L282`).
Older payloads without the new fields render `Unknown`, `Not recorded`, or
`Not collected` states rather than fabricating zeros.

## 4. Navigation

Session rows link to `#session=<percent-encoded-session-id>`. The generated
artifact remains one HTML file and direct hashes work without a server (#310).

The shell gains a router with three inputs: initial `location.hash`,
`hashchange`, and `popstate`. It recognizes only the `session` key. A known
session ID renders `renderSessionDetail(container, session, routeState)`; an
unknown or dashboard-window-excluded ID renders an explicit not-found page with
a link back to the session list. Values are compared as strings and escaped
before display.

Opening a session from a dashboard row uses `history.pushState()` and stores
the originating view plus any serializable view state explicitly handed to the
shell. Browser Back restores that view and its period selection where
practical. Directly opening a session hash uses the default Overview return
target. The route does not encode filter state in the hash for this release.

## 5. Session page interaction model

### 5.1 Stable page regions

The page is scan-first and uses this order:

1. header, breadcrumb, and fixed session facts;
2. whole-session token overview and selection brush;
3. root/subagent activity tracks and recursive filter tree;
4. `All` / `By time period` scope toggle, scoped detail chart, and totals;
5. effort/model/token-component breakdowns;
6. expandable Skills, Commands, MCP, Agent hierarchy, and Session facts cards;
7. expandable chronological event ledger.

Compact cards show counts and status, never top-N slices. Expanding a card
shows every record in the current scope. Full detail remains available even
when charts must bucket dense data (#310).

### 5.2 Whole-session overview

The overview's x-domain always spans the complete session. It plots the exact
responses from currently active agent paths, grouped into adaptive time
buckets and split by effort. Bucket boundaries are shared by every effort
series. Stacking is computed from common cumulative boundaries, so independent
curves cannot create gaps or overlaps between effort bands (#310).

Bucket duration is chosen from a fixed duration ladder so the number of buckets
does not exceed the chart's pixel budget. Every response enters one half-open
bucket `[start, end)`, with the final bucket including the session endpoint.
Bucket totals are sums of exact response totals and must reconcile with the
active-agent session total. Resizing may change bucket boundaries but never the
underlying total.

The selected time interval is a brush overlay on the whole-session chart; it
does not replace or crop that chart. Pointer dragging and keyboard-adjustable
range controls manipulate the same inclusive-start/exclusive-end interval. The
default interval is the complete session.

### 5.3 Scoped detail and exact bars

Below the overview, a second chart renders the response set selected by the
high-level scope control. In `All`, this is the complete session and moving the
brush does not change it. In `By time period`, this is the brush interval. The
chart uses exact response bars when the included responses fit at a minimum
width of 12 CSS pixels per bar. Otherwise it remains adaptively bucketed and
shows `Zoom further for per-response bars`. The 12-pixel rule is based on the
plot's measured width, so the behavior is deterministic at each viewport size.

Each exact bar represents one deduplicated response and exposes timestamp,
full and normalized model, effort, agent path, and all token components on
hover and keyboard focus. A textual table exposes the same fields. Color is
supplemental: effort and model always have labels or patterns.

### 5.4 `All` / `By time period`

This two-state control governs the analytics below the whole-session overview:

- `All` uses every response and deterministic event from active agent paths,
  regardless of the current brush interval.
- `By time period` uses only active-agent records whose timestamps fall within
  the brush interval.

Changing this toggle recomputes the scoped detail chart, summary cards,
effort/model/token-component totals, expanded activity lists, and the event
ledger. It does not change the overview's full-session time domain, the brush
itself, or fixed identity facts. The page labels every changing total with its
active scope (#310).

### 5.5 Nested agent filter

The agent selector is a tree built from exact `agent_path` arrays. It starts
with every node active. Each node has three visual states:

- checked: the node and every descendant are active;
- unchecked: the node and every descendant are inactive;
- indeterminate: at least one but not all members of the subtree are active.

Activating or deactivating a node applies to that node and its full descendant
subtree. A child can then be toggled independently, which updates each ancestor
to checked, unchecked, or indeterminate. Filtering is by full path, not leaf
agent name, so repeated agent types in separate branches stay independent.

The combined token overview, range chart, token rollups, skills, commands where
attributable, MCP calls, and ledger are projections of the active path set.
Fixed identity facts do not change. If all paths are disabled, charts and
scoped panels show an explicit `No agents selected` state with a `Select all`
action (#310).

Commands currently belong to the root transcript only. They are included when
the root path is active and excluded when it is inactive; no command is
attributed to a child without recorded evidence
(`src/claude_prospector/parser.py:L361-L379`).

### 5.6 Concurrent activity tracks

The combined overview does not imply that only one model or effort was active
at a time. Each observed agent path gets its own horizontal activity track.
Response marks on that track show time, model, effort, and token magnitude.
Tracks may overlap in time because root and subagent transcripts can be
concurrent. The tree checkbox associated with a track is the filter control
described above (#310).

## 6. Deterministic event ledger

The ledger merges response, Skill, Command, and collected MCP records and sorts
them by:

1. timestamp;
2. event-kind order (`response`, `skill`, `command`, `mcp`) solely as a stable
   tie-breaker; and
3. original per-source ordinal.

The event-kind tie-breaker is display ordering, not a claim of causality.
Ledger entries contain only the fields defined in section 3. They never contain
assistant text, user text, thinking, command arguments, tool inputs, or tool
results. The ledger respects both the active-agent set and the high-level scope
toggle; fixed session facts remain outside it.

## 7. Client architecture

Add `static/views/session-detail.js`, inline it from `renderer.py`, and expose
`renderSessionDetail` in the same package-resource convention as the existing
views (`src/claude_prospector/renderer.py:L120-L129`,
`tests/test_phase3_views.py:L128-L173`). Shared pure functions for range
selection, bucketing, reconciliation, tree-state propagation, and event
projection live under `window.CP` in `cp-utils.js`; the renderer consumes their
results without mutating `window.DATA`.

All filtering and bucketing happens in memory over the exact embedded records.
No UI interaction rescans transcript files. Chart instances and DOM listeners
are destroyed when leaving the session route so browser Back/Forward does not
accumulate handlers.

Transcript-derived strings use text nodes or the existing escaping helper.
They are never interpolated into raw HTML. The renderer's script-context
escaping remains the outer payload defense
(`src/claude_prospector/renderer.py:L102-L114`).

## 8. Accessibility and responsive behavior

- Route changes move focus to the session heading and announce not-found and
  empty states.
- Agent nodes use native checkboxes with `indeterminate`, tree labels, visible
  focus, and keyboard-operable expansion.
- The range brush has labeled start/end controls and an accessible current
  interval description.
- Every chart has a nearby textual summary; exact response data is always
  available in a table.
- Effort and model distinctions use text plus color/pattern, never color alone.
- Narrow layouts stack summary cards, keep track labels readable, and allow the
  detailed tables to scroll horizontally without clipping page controls.

These are acceptance requirements from #310, not optional visual polish.

## 9. Error and missing-data states

| Condition | Required rendering |
|---|---|
| Unknown or out-of-window hash | `Session not found in this dashboard` and route back |
| No valid effort on a response | `Unknown` effort bucket |
| Legacy payload lacks exact fields | Explicit unavailable label; never reconstructed from aggregate ratios |
| No active agents | `No agents selected` and `Select all` |
| Selected period has no records | Empty period state; whole-session overview remains visible |
| MCP calls not opted into | `Not collected` |
| MCP collection requested but transcript unreadable | `Unavailable` plus warning |
| MCP collected with no calls | `0 calls` |
| Result sizes not opted into | Size column hidden or labeled `Not collected` |
| Result size excluded/unmatched | Existing unavailable/excluded wording; never `0` |
| Skill/command field absent | `Not recorded` for legacy payload; empty list only when collection was definitive |

## 10. Reconciliation invariants

The following invariants are release-blocking:

1. A response's `total_tokens` equals input + output + cache read + cache
   creation (`src/claude_prospector/models.py:L40-L47`).
2. Summing all response totals for a session equals the existing session total
   (`src/claude_prospector/aggregator.py:L263-L275`).
3. Grouping the same response set by effort, normalized model, agent path, or
   token component does not change the applicable total.
4. Bucketing changes only presentation; the sum of bucket totals equals the sum
   of their source responses.
5. The active-agent response set is the union of exact selected paths, with no
   ancestor roll-up records added. Parent paths and descendant paths represent
   separate recorded messages, so each response appears once.
6. `All` and `By time period` differ only by the time predicate; they use the
   same active-agent predicate.
7. Skill and MCP records are deduplicated by tool-use identity independently of
   response message-ID deduplication.

The existing `agent_tokens` contract already accumulates every observed path's
real message tokens rather than redistributing parent totals
(`src/claude_prospector/aggregator.py:L220-L249`). The session page preserves
that exact-attribution rule.

## 11. Test strategy

Implementation follows TDD and adds tests at each layer (#310):

### Parser and models

- effort extraction for valid, missing, blank, non-string, future-label, and
  mid-session values;
- duplicate fragments with consistent, missing-then-present, and conflicting
  effort;
- multiple Skill blocks across repeated fragments, including missing tool IDs;
- root and nested metadata observations; and
- ToolUseRecord timestamps.

### Aggregation and collection

- exact response payload shape and backward-compatible existing keys;
- reconciliation across effort, model, agent, token component, and session;
- short, long, root-only, concurrent multi-agent, and deeply nested fixtures;
- complete per-session Skill and Command activity;
- MCP states for disabled, collected-zero, collected-calls, unreadable, and
  result-size-enabled modes; and
- proof that per-session MCP retention does not change global MCP totals.

### Client and routing

Calculation and state transitions are pure JavaScript functions. Add a
dependency-free Node test harness and pin an explicit Node version in CI rather
than relying on source-containment assertions. Tests cover adaptive bucket
boundaries and totals, the 12-pixel exact-bar threshold, brush predicates,
`All` / `By time period`, recursive checked/unchecked/indeterminate propagation,
full-path filtering, empty states, and ledger ordering. The existing repo notes
that current view tests do not execute JavaScript
(`tests/test_mcp_usage_view.py:L1-L20`), so this feature must add execution
coverage to satisfy #310 rather than repeat that limitation.

Rendered-HTML tests cover direct hashes, unknown IDs, Back/Forward state hooks,
escaping, resource inclusion, and accessibility attributes. A browser smoke
test verifies pointer and keyboard range controls, agent toggles, expansion,
focus movement, and history behavior. Existing dashboard snapshot, packaging,
CLI JSON, and end-to-end suites remain green.

## 12. Documentation and rollout

Update README dashboard sections to describe session links, recorded-effort
semantics, the distinction between `All` and `By time period`, recursive
subagent filtering, and `Not collected` MCP behavior. The existing README
already presents session drill-down and both MCP flags
(`README.md:L75-L89`, `README.md:L239-L306`), so the new documentation extends
those sections instead of adding a separate setup flow.

The feature ships as an additive schema and UI route. There is no migration,
new server, new default data collection, or per-session output file. MCP call
and result-size collection stay opt-in exactly as required by #310.

## 13. Out of scope

- inferred intent, quality, action summaries, drift, or recommendations;
- prompt, thinking, command-argument, tool-input, or tool-result content;
- enabling either MCP collection mode by default;
- cross-session effort trends or comparisons;
- standalone session HTML files or a dashboard web server; and
- changing the transcript walk depth cap or traversal semantics.
