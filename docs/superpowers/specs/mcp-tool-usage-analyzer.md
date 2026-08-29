---
title: MCP tool-usage analyzer (tool-usage subcommand, per-agent / per-session / per-server)
touches:
  - src/claude_prospector/transcript_walker.py
  - src/claude_prospector/tool_collection.py
  - src/claude_prospector/mcp_names.py
  - src/claude_prospector/cli/tool_usage.py
  - src/claude_prospector/__main__.py
  - src/claude_prospector/parser.py
  - src/claude_prospector/models.py
  - src/claude_prospector/aggregator.py
  - src/claude_prospector/cli/session_summary.py
  - tests/test_transcript_walker.py
  - tests/test_mcp_names.py
  - tests/unit/test_tool_collection.py
  - tests/unit/test_tool_usage.py
  - tests/test_aggregator_tool_usage.py
  - tests/test_cli_subcommands.py
  - README.md
skills_relevant:
  - python
---

# MCP tool-usage analyzer — implementation spec (issue #195)

**Status: IMPLEMENTED** (Phases 0–2; §8 Phase 3 shipped under #248 via
PRs #259–#261). All eight decisions in §6 were resolved by the user on
2026-08-21 and are recorded there as **RESOLVED** with their rationale. §5
requirements, §7 schema, and §8 phasing reflect the resolved answers. Issue
#195 is closed.

Implementation history: #249 (`mcp_names.py`), #250 (`transcript_walker.py`
extraction), #251 (`tool_collection.py`), #252 (aggregator + CLI); tracked
under issue #195.

**`tests/test_parser.py` is deliberately absent from `touches:`.** The walker
extraction must leave it byte-identical; that is the Phase 1a gate, not an
omission.

**Highest-risk item:** D2 resolved to **(c) extract a shared transcript walker**,
which refactors `parser.py`'s subagent recursion (`parser.py:406-546`) — the
most-tested logic in the repo — rather than adding a flag to it. §8 Phase 1 makes
`tests/test_parser.py` passing **unchanged** a hard gate before any `tool_use`
collection work builds on top.

Primary spec source: issue #195 body (fetched 2026-08-21 via the public issue
page; state `open`, no labels, no milestone, no comments). Related: issue #248
(open, filed 2026-08-08 — dashboard surface) and issue #241 (**closed as not
planned**, folded into #195).

---

## 1. What this is, and what it is not

`claude-prospector tool-usage` is a **read-side aggregator over transcripts that
Claude Code has already written**. It adds no runtime instrumentation, no hook,
and no new on-disk state.

Three facts bound the work:

1. **Classification already exists.** `_normalize_mcp_tool_name`
   (`src/claude_prospector/cli/session_summary.py:227-272`) already resolves both
   MCP naming forms — `mcp__plugin_<plugin>_<server>__<method>` and
   `mcp__<server>__<method>` — to `"<server>.<method>"`, returning `None` on
   malformed names. Issue #195's implementation note "MCP naming convention must
   be abstracted into a resolver function" is **already satisfied**. Do not write
   a second resolver.
2. **Per-agent attribution already exists.** `_parse_subagents_recursive`
   (`src/claude_prospector/parser.py:406-546`) builds the root→leaf `agent_path`
   tuple from `subagents/*.meta.json`, and `_path_key`
   (`src/claude_prospector/aggregator.py:24-40`) joins it into the `by_agent` key
   used everywhere else. Issue #195's caveat "parent-agent attribution requires
   correct nesting traversal" is **already satisfied for the `subagents/` tree**
   — but see the `workflows/` gap in §5.3.
3. **Nothing aggregates tool calls.** `parser.py` reads only
   `usage` + `model` off assistant entries (`parser.py:340-347`) and never looks
   at `tool_use` blocks. There is no `by_tool` / `by_server` anywhere in
   `aggregator.py` (`AggregateResult`, `aggregator.py:43-57`).

So the actual new work is: **collection with correct attribution + aggregation +
CLI + (deferred) dashboard surfacing.**

### Issue boundary

| Issue | Scope | This spec |
| --- | --- | --- |
| #195 | Data layer + `tool-usage` CLI + JSON contract | **In scope** |
| #248 | Dashboard panel (`renderer.py`, `templates/dashboard.html`, `static/views/`) | **Shipped** — §8 Phase 3, PRs #259–#261 |
| #241 | Runtime MCP call tracking | Closed as not planned; only its `--track-mcp-calls` requirement survives, and its meaning is disputed — see D1 |

---

## 2. Discovery: the transcript-format probe

Issue #195 leaves one open question:

> **Open question:** Does "sessions_seen_in" data exist in transcripts, or
> requires cross-reference with dated `settings.json` MCP config?

**Answer: it exists in transcripts. No `settings.json` cross-reference is
needed — and a `settings.json` cross-reference would in fact be *wrong*, because
it reflects config at read time, not at session time.**

### 2.1 Probe methodology (reproducible)

Empirical probes run 2026-08-21 against local transcripts under
`~/.claude/projects/**`, Claude Code version `2.1.225` (read off the `version`
field on every entry). These are user-local, rotating files — a reviewer should
re-run the probe rather than trust the paths. Probe patterns, in order:

| # | Pattern (ripgrep, over `*.jsonl`) | Purpose |
| --- | --- | --- |
| P1 | `"type":"[a-zA-Z_-]+"` (`-o`) | Enumerate entry / attachment types |
| P2 | `"mcp_instructions_delta".{0,400}` (`-o`) | Server-level availability shape |
| P3 | `"deferred_tools_delta".{0,400}` (`-o`) | Tool-level availability shape |
| P4 | `"name":"mcp__[a-zA-Z0-9_]+"` (`-o`) | Actual MCP invocations |
| P5 | `"id":"msg_[A-Za-z0-9]+"` + `"toolu_[A-Za-z0-9]+"` (`-o -n`) | Fragment-line / dedup shape |
| P6 | `"[a-zA-Z]+":\{"type":"deferred_tools_delta"` (`-o`) | Attachment wrapper key |

### 2.2 What the probes found

**Availability IS recorded, as `attachment` entries.** P1 surfaced attachment
sub-types that no current code path reads:
`deferred_tools_delta`, `mcp_instructions_delta`, `agent_listing_delta`,
`skill_listing`, `command_permissions`, `tool_reference`.

**Verified access path** (probe P6, `"[a-zA-Z]+":\{"type":"deferred_tools_delta"`
and the same for `mcp_instructions_delta`; both matched
`"attachment":{"type":"..."}`):

```
entry["type"]                        == "attachment"
entry["attachment"]["type"]          == "deferred_tools_delta" | "mcp_instructions_delta"
entry["attachment"]["addedNames"]    -> list[str]
entry["attachment"]["removedNames"]  -> list[str]
entry["attachment"]["addedBlocks"]   -> list[str]   # instructions text; ignore
```

Do not guess this shape — a fixture built on the wrong wrapper key passes T7/T8
while the real parse silently returns nothing.

- **`deferred_tools_delta`** carries `addedNames` — a flat array of tool names
  including fully-qualified MCP names. Observed verbatim (P3, truncated):
  `"deferred_tools_delta","addedNames":["EnterWorktree","ExitWorktree","Monitor",
  "SendMessage","TaskStop","WebFetch","WebSearch","mcp__azure__acr",
  "mcp__azure__advisor","mcp__azure__aks",...]`.
  Every occurrence also carries a `removedNames` key (P3 vs. a `"removedNames"`
  count probe returned 25 and 25 across the same 14 files) — so it is a genuine
  **delta stream**, not a one-shot snapshot.
- **`mcp_instructions_delta`** carries server-level `addedNames`, e.g.
  `["azure","codegraph","excalidraw","open-design","plugin:microsoft-docs:microsoft-learn"]`.
- **`tool_reference`** records a `ToolSearch` resolution, with
  `toolUseResult.total_deferred_tools` (observed: `228`) — a corroborating
  denominator.

**The signal is present in sub-agent transcripts too**, which is what makes
per-agent availability possible at all. A sub-agent transcript
(`.../subagents/agent-aafbbbfb08dfe7fc1.jsonl`) contained exactly one
`deferred_tools_delta` and **zero** `mcp_instructions_delta`, and its
`addedNames` list was materially shorter than the root session's — a handful of
built-ins plus the azure family, versus the root's 228. **Inference: the delta
reflects each agent's own tool grant, not the session's.** This is load-bearing
for the `--agent` acceptance criterion.

**No eager-load counter-example found.** The one MCP invocation in session
`748a45f2-…` (P4: `"name":"mcp__github__create_issue"`) was present in that
session's deferred inventory (the file contains 146 `mcp__github__` occurrences,
all but one inside `addedNames`). So on this host, at this version, every MCP
tool that was *called* was also *listed*. That is consistent with — but does not
prove — completeness.

### 2.3 The precondition, and why the field must be nullable

`deferred_tools_delta` only enumerates **deferred** tools. If tool-search
deferral is off, or a server is eagerly loaded, its tools live in the system
prompt, which is never written to the JSONL. Availability then becomes
**invisible**, not zero.

That distinction is the whole point of the field. `sessions_seen_in` exists to
power the dormant-server prune case — issue #195's own example is
`azure: {total_calls: 0, sessions_seen_in: 9}`. If a missing signal is rendered
as `0`, an available-but-unused server silently drops off the prune list, which
is precisely the recommendation the field was added to produce.

**Requirement:** `sessions_seen_in` is `int | null`.
- `null` — no availability signal in any transcript in the window; the analyzer
  could not tell.
- `0` — signal present in ≥1 session's transcripts, and this server was absent
  from all of them.
Same rule for `avg_calls_per_active_session` when `sessions_used_in` is 0.

**Requirement:** the JSON envelope carries an `availability_signal` block
(§7) stating how many sessions in the window carried the signal, so a consumer
can judge coverage instead of guessing.

### 2.4 Version-drift caveat

The corpus probed in §2.1 is entirely Claude Code `2.1.225` (per the `version`
field read on every entry, §2.1). A probe for `"version":"(1\.|2\.0\.)` across
that same corpus returning no matches is therefore not meaningful evidence of
anything — it could not have matched, because no file in the corpus carries any
version other than `2.1.225`. It does **not** establish that older-version
transcripts lack these attachment types, nor when they were introduced
upstream. Implementation must treat their absence as "signal missing"
(→ `null`), never as an error and never as `0`.

`unverified:` the Claude Code version that introduced `deferred_tools_delta` /
`mcp_instructions_delta` is not documented in any source checked. If the
`null`-vs-`0` semantics above are honoured, this does not need to be resolved.

---

## 3. Reuse boundary — what to reuse and what NOT to

This section exists because "reuse the existing classifier" is a trap. Two of the
three functions in that module will silently corrupt the numbers this analyzer
is built to produce.

### ✅ Reuse

| Symbol | Location | Why |
| --- | --- | --- |
| `_normalize_mcp_tool_name` | `cli/session_summary.py:227-272` | The server/method resolver. Handles both naming forms, returns `None` on malformed names. **D5 = (b):** promoted to public `normalize_mcp_tool_name` in `mcp_names.py`, re-exported from `session_summary` for compatibility. |
| `_parse_subagents_recursive` / `agent_path` | `parser.py:406-546` | The per-agent attribution mechanism — including the depth cap, cycle defense, and one-warning-per-session de-dup flags. **D2 = (c):** this logic is *extracted* into `transcript_walker.py` and driven by visitors, not duplicated and not re-derived. Behaviour must be bit-identical after extraction (§8 Phase 1 gate). |
| `_path_key` | `aggregator.py:24-40` | The `by_agent` key format. Reusing it makes `by_agent` in this analyzer join cleanly against `AggregateResult.by_agent`. |
| `compute_skill_adoption` wiring pattern | `aggregator.py:241-293` + `cli/dashboard.py:170-179` | Precedent for a self-contained aggregator attached conditionally to `AggregateResult`. |

### ❌ Do NOT reuse — with the reason

**`_collect_tool_uses` (`cli/session_summary.py:394-424`) must not be used by
this analyzer.** Two independent count-corrupting behaviours:

1. **It drops the tools the issue wants counted.** `SKIPPED_TOOLS`
   (`session_summary.py:33-43`) excludes `Read`, `Grep`, `Glob`, `WebFetch`,
   `WebSearch`, `Skill`, `TodoWrite`. Issue #195's own `by_tool` example is
   `{"Read": 8421, "Grep": 4112, ...}`. Reusing this collector returns zero for
   the two largest buckets in the spec's own example output.
2. **It destroys call frequency.** `_collapse_consecutive`
   (`session_summary.py:368-391`) drops any record adjacent to one sharing
   `(type, target)`. Ten consecutive `mcp__codegraph__codegraph_explore` calls
   collapse to one. Frequency is the single quantity this analyzer measures.

Both behaviours are *correct* for `session-summary` (a human-readable recap) and
*wrong* here. The new collector is a separate, deliberately dumb function:
count every `tool_use` block, skip nothing, collapse nothing.

**`_classify_tool_use` (`session_summary.py:275-365`)** is borderline: it returns
`None` for `SKIPPED_TOOLS` (defect #1 above) and produces prose `summary`
strings this analyzer does not need. Prefer a thin new classifier that calls
`_normalize_mcp_tool_name` directly.

---

## 4. Correctness hazards discovered during probing

These are not hypothetical. Each was verified against a real transcript on
2026-08-21 (v2.1.225).

### 4.1 A multi-block assistant message is written as N JSONL lines — and the
existing dedup would drop N−1 of them

Probe P5 on `.../subagents/agent-aafbbbfb08dfe7fc1.jsonl`:

- `message.id` repeats across 2–6 consecutive lines
  (`msg_011CeFpRKrfRzX5ReA9EqsrB` spans lines 25, 26, 28, 30, 32, 34).
- The `toolu_` ids on those lines are **different** — line 5 carries
  `toolu_01MPGWY8Z3vKcddiiR3vVHij`, line 6 carries
  `toolu_019x3K4jQx2gbbnZzaE5HJX2`, and each reappears exactly once more on the
  following `user` line as the `tool_result`'s `tool_use_id`.

**Conclusion: each assistant JSONL line carries one content block. Parallel tool
calls in a single assistant turn are written as consecutive lines sharing one
`message.id`, each holding a distinct `tool_use` block.**

This inverts the naive assumption. The hazard is `parser.py:353-360`:

```python
if message_id is not None and message_id in message_indexes:
    ...
    # Fragment lines repeat the message's final usage snapshot;
    # summing duplicate IDs would multiply every usage field.
    continue
```

That `continue` is correct for **token** accounting (it is the fix from commit
`766acba`, "dedup assistant messages by message.id to stop token-usage
inflation"). It is **fatal** for tool accounting: bolting `tool_use` collection
in after that guard silently discards every parallel tool call but the first.

**Requirements:**
- If collection lives inside `_parse_jsonl_messages`, it must run **before** the
  `message_id` dedup `continue`.
- Dedup tool calls by **`tool_use.id`** (the `toolu_…` value), never by
  `message.id`.
- A regression test must encode this exact shape (§9, T2).

### 4.2 Skipping `tool_use` blocks on non-assistant entries

Only `entry["type"] == "assistant"` entries carry `tool_use` blocks; the
matching `tool_result` on the following `user` entry carries the same
`tool_use_id` (P5). Counting both double-counts every call. Filter on
`entry.type == "assistant"` and `block.type == "tool_use"`, exactly as
`_collect_tool_uses` does (`session_summary.py:409-420`) — that part of it is
right.

### 4.3 `subagents/workflows/wf_*/` agents are invisible to the parser today

Confirmed on 2026-08-21:

- Real transcripts exist at
  `~/.claude/projects/<slug>/<session>/subagents/workflows/wf_<id>/agent-<id>.jsonl`,
  each with a sibling `agent-<id>.meta.json` (21 such meta files in one
  wayfinder session alone, across 5 `wf_*` directories).
- `_parse_subagents_recursive` globs `subagent_dir.glob("*.meta.json")`
  (`parser.py:507`) — **non-recursive, at the `subagents/` level only** — and
  recurses only into `subagents/<agent_id>/` (`parser.py:532`). The
  `workflows/` directory is never entered.
- `grep -c workflows src/claude_prospector/parser.py` → **0 matches**. There is
  no handling of any kind.

**Consequence:** workflow-nested agents' messages are absent from *all* current
prospector output — tokens included, not just this new feature. Issue #195's AC
"`--agent code-writer` correctly attributes calls to sub-agent runtime" is
therefore **partially unmeetable** for any agent dispatched inside a workflow.

**Disposition:** out of scope for #195; **file a sibling issue** (§10). The
`tool-usage` output must document the omission rather than silently under-report
— see the `warnings` field in §7.

### 4.4 `--track-mcp-calls` gates nothing on the read side

Issue #195 lists `--track-mcp-calls` as an opt-in flag (default off) and the AC
says "Collection gated behind opt-in flag (default off)". That requirement is
inherited verbatim from **#241, which proposed *runtime* tracking and was closed
as not planned**. On the read side there is no collection step to gate: Claude
Code already wrote these transcripts, and `session-summary` already parses
`tool_use` blocks today with no flag at all
(`session_summary.py:394-424`, shipped).

Requiring `--track-mcp-calls` for a subcommand whose only function is MCP
analysis makes the command a no-op by default.

**Resolved (D1 = a):** the flag is **dropped from `tool-usage` entirely** and
moves to `dashboard` (#248), default off, where it gates whether MCP data appears
in dashboard output. Issue #195's AC bullet "Collection gated behind opt-in flag
(default off)" should be edited on the issue to say so.

---

## 5. Requirements (confirmed 2026-08-21)

### 5.1 Functional

- **F1** New subcommand `tool-usage`, registered in `__main__.py` via the
  established three-line pattern (import at `__main__.py:8-16`, `build_parser`
  at `:40-46`, dispatch at `:54-73`).
- **F2** Emits JSON to stdout (schema §7). **JSON-only for v1 (D4)** — no
  `--format table`, no human-readable renderer. `--format json` is accepted as a
  no-op alias for forward compatibility with issue #195's proposed command line.
- **F3** Filters: `--days N` (default 7), `--repo <name>`, `--agent <name>`,
  `--tool <glob>`, `--server <name>`. Issue #195 defines `--server` as sugar for
  `--tool mcp__<server>__*`; the implemented glob is **widened to
  `mcp__*<server>__*`** because the literal form cannot match the plugin-scoped
  naming (`mcp__plugin_github_github__create_issue`), making `--server github`
  silently return nothing for every plugin-hosted server. The cost is that a
  hypothetical `mcp__plugin_x_notazure__y` would also match `--server azure`;
  a false positive on a contrived name is preferable to a silent false negative
  on a real one. `--tool` and `--server` are mutually exclusive.
  Also `--data-dir` for parity with every other subcommand
  (`cli/dashboard.py:77-80`), and `--compact` per F6.
  **No `--track-mcp-calls` (D1 = a)** — the subcommand runs unconditionally.
  **`--agent <name>` matches any segment of the agent path:** `<name>`
  matches when it appears anywhere in the root→leaf `agent_path` ancestry
  (`_matches_agent` in `tool_collection.py`), not only the leaf (rightmost)
  segment — e.g. `--agent general-purpose` matches calls attributed to
  `general-purpose→code-writer`. Filtering happens at record level, before
  aggregation: only `ToolUseRecord`/`AgentAvailability` entries whose
  `agent_path` contains `<name>` are kept, and the filtered set is handed to
  the normal aggregation unchanged. Consequently `by_agent` retains each
  distinct matching path as its own key — no leaf-name collapsing, no
  cross-path summing — and `sessions_seen_in` / `sessions_used_in` /
  `avg_calls_per_active_session` fall out of the ordinary per-session
  aggregation loop: a session contributes to those counters at most once no
  matter how many matching agent paths it contains, so no separate union
  step exists or is needed for the `--agent`-filtered case.

  **Reconciliation note (issue #258):** this paragraph previously documented
  leaf-name-only matching plus a union-based session-metric aggregation for
  agents sharing a leaf name — neither of which was ever implemented. The
  shipped `_matches_agent` helper has always matched any segment of the
  ancestry tuple. The maintainer decided the shipped any-segment behavior is
  correct; this spec is corrected to match it rather than the reverse.
- **F4** `by_tool` counts **every** tool, MCP and built-in alike, keyed by raw
  tool name (issue #195's example includes `Read` and `Grep`).
- **F5** `by_server` rolls up MCP calls via `normalize_mcp_tool_name`
  (`mcp_names.py`, D5 = b), with `total_calls`, `sessions_seen_in` (nullable,
  §2.3), `sessions_used_in`, `avg_calls_per_active_session` (nullable when
  `sessions_used_in == 0`), and `by_method`.
- **F6** `by_agent` is keyed by the `AGENT_PATH_SEPARATOR`-joined `agent_path`
  (`aggregator.py:24-40`), so keys join against existing dashboard `by_agent`
  keys. **D3 = (c):** the **default** shape is the full
  `by_agent[agent][raw_tool_name]` breakdown exactly as issue #195 specifies;
  `--compact` switches to `by_agent[agent][server]` for MCP calls plus a single
  `_builtin` bucket aggregating all non-MCP tools. `--compact` changes only
  `by_agent`; `by_tool` and `by_server` are unaffected.
- **F7** Availability derived from `deferred_tools_delta` **and**
  `mcp_instructions_delta` attachment entries at the **verified access path in
  §2.2** (`entry["attachment"]["addedNames"]`, guarded by
  `entry["type"] == "attachment"` and `entry["attachment"]["type"]`), applying
  `addedNames` / `removedNames` **in file order** (they are deltas, §2.2).
  **D6 = union:** a server is available if **either** source names it — they
  have complementary blind spots (instructions-less servers vs. eagerly-loaded
  tools), so a disagreement is a coverage gap in one source, not a contradiction.
  Record which source(s) confirmed each observation in
  `availability_signal.sources`.
  Availability is computed **per agent transcript**, then rolled up to the
  session by union per **D8 = (a)**: a server counts as seen in a session if it
  was available to **any** agent in that session. Per-agent availability is
  retained internally so `--agent <name>` narrows to that agent's own grant.
  **Canonical `by_server` key mapping:** availability-signal server strings —
  `mcp_instructions_delta.addedNames` entries (server-level, e.g.
  `plugin:microsoft-docs:microsoft-learn`) and `deferred_tools_delta.addedNames`
  entries (tool-level, fully-qualified names like `mcp__azure__advisor`) — must
  be routed through the same server-extraction logic `normalize_mcp_tool_name`
  uses to pull a server component out of call names, rather than a separate
  alias table. This guarantees availability data and call data land on one
  canonical `by_server` key instead of two representations of the same server
  producing duplicate or mismatched entries. When this is implemented (Phase
  1b / Task 3-4), add a plugin-scoped availability fixture exercising a
  `plugin:<plugin>:<server>`-shaped `mcp_instructions_delta` name alongside its
  corresponding `mcp__plugin_<plugin>_<server>__<method>` call name, and assert
  both resolve to the same `by_server` key.
- **F7a** Availability is time-filtered by the session's inclusion in the
  window, not per-entry: the delta entries appear once near the start of a
  transcript and carry timestamps that may fall outside a narrow `--days`
  window. Filtering them per-entry would blank the signal for long sessions.
- **F10** Session selection reuses `parse_sessions`, and therefore inherits the
  `project_exclude_patterns` filtering from `config.json`
  (`parser.py:667-670,702-703`) — a project hidden from the dashboard is also
  absent from `tool-usage`, and from `window.sessions`. This is a deliberate
  consistency choice; if a raw-corpus view is wanted, add `--no-exclude` rather
  than diverging silently.
- **F11** Time filtering reuses `_parse_window` and `_parse_date`
  (`cli/dashboard.py:19-61`). `--days N` from issue #195 is sugar for
  `--window <N>d`; `--from` / `--to` are accepted for parity. Introducing a
  third independent time idiom is a defect, not a feature.
- **F8** Missing / unreadable / non-JSONL transcripts are skipped without
  aborting the run, and counted in `warnings` (§7). Issue #195: "Sessions with
  missing transcripts should be skipped gracefully."
  **Partial/all-invalid transcripts:** a transcript file containing a mix of
  valid and malformed JSONL lines is not skipped — its valid lines are still
  processed normally, and malformed lines are silently skipped line-by-line,
  matching existing `session_summary.py` behaviour. `window.sessions_skipped`
  increments only when a transcript file has **zero** valid lines (every line
  in it is malformed or unparseable) — not merely when it contains any
  malformed line.
- **F9** Malformed MCP names — a raw tool name that **starts with `mcp__`** but
  for which `normalize_mcp_tool_name` returns `None` — are counted in `by_tool`
  under their raw name, excluded from `by_server`, and increment
  `warnings.malformed_mcp_names`. `normalize_mcp_tool_name` also returns `None`
  for ordinary non-MCP tool names (`Read`, `Grep`, etc.); those must **not**
  increment `warnings.malformed_mcp_names` — the counter is scoped to names
  that look like MCP calls but fail to parse, not to every `None` return.
- **F12** (D2 = c) A shared transcript walker in
  `src/claude_prospector/transcript_walker.py` (traversal only) owns the
  `subagents/` recursion,
  `agent_path` construction, depth cap, cycle defense, and the
  one-warning-per-session de-dup flags currently inside
  `_parse_subagents_recursive` (`parser.py:406-546`). `parser.py` (token records)
  and `tool_collection.py` (tool calls + availability) drive it with different
  visitors. **Extraction is behaviour-preserving:** `tests/test_parser.py` must
  pass unchanged (§8 Phase 1a).
- **F13** (D7) No token-cost-per-tool-call metric in `tool-usage` output. Deferred
  to #248, where it must ship as an explicitly-labelled proxy or be dropped.
  **Resolved under issue #262**, not #248: shipped as the explicitly-labelled
  proxy option (M4 — a `tool_result` payload-size estimate,
  `estimated_result_tokens`/`cost_attribution`), gated behind the `dashboard`
  `--track-mcp-call-sizes` flag (metric choice D-1=M4 and the privacy-posture
  D-4 resolution recorded in issue #262 and PR #270; proxy-labelling output
  shape in PRs #271, #272).

### 5.2 Non-functional

- **N1** Read-only. No writes outside stdout. No network.
- **N2** No new runtime dependency.
- **N3** Exit-code constants at module level (`EXIT_OK = 0`,
  `EXIT_IO_FAILURE = 1`), matching `session_summary.py:23-26`,
  `session_audit.py`, `variance_save.py`, `drift_report.py`.
- **N4** Google-style docstrings, frozen slotted dataclasses for records
  (`models.py:9-38` convention), full type hints. Lint gate is **both**
  `uv run ruff check .` **and** `uv run ruff format --check .` (CLAUDE.md
  § CI gates).
- **N5** Performance: the walker extraction (D2 = c) must not regress
  `dashboard` runtime. Because the extraction is behaviour-preserving and
  `parser.py` keeps its existing visitor, the expected delta is ~0; a measured
  before/after `dashboard --format json` run on the local corpus is a Phase 1
  merge gate to confirm it.
- **N7** (D2 = c) The walker is a **pure refactor target**, not a redesign. Do
  not "improve" the depth cap, the cycle defense, the warning text, or the
  `unknown` agent-type fallback while extracting. Behaviour changes to that
  logic — including fixing the `workflows/` gap (§4.3) — belong to their own
  issue and PR.
- **N6** Privacy: tool **names** and **counts** only. No `tool_use.input`
  payloads in output — file paths and shell commands leak. (Precedent: the
  `--redact-prompts` opt-out added in commit `ad1f3b9` for `variance-save`
  treats prompt text as sensitive by default.)

---

## 6. Decisions — RESOLVED 2026-08-21

All eight resolved by the user. Each row records the chosen option, where it
lands in the spec, and what it displaces. Options not chosen are summarised for
provenance; the full option analysis is in this file's git history.

| # | Question | **Resolved** | Lands in |
| --- | --- | --- | --- |
| D1 | What does `--track-mcp-calls` gate? | **(a)** Drop from `tool-usage` entirely; moves to `dashboard`/#248, default off | §4.4, F3 |
| D2 | Where does `tool_use` collection live? | **(c)** Extract a shared transcript walker | F12, N5, N7, §8 Phase 1 |
| D3 | `by_agent` granularity | **(c)** Full `[agent][tool]` by default, `--compact` for `[agent][server]` + `_builtin` | F6, §7 |
| D4 | Human-readable output? | **JSON-only for v1.** No `--format table` | F2 |
| D5 | Where does the resolver live? | **(b)** Public `normalize_mcp_tool_name` in `mcp_names.py`, re-exported | §3, F5, §8 Phase 0 |
| D6 | Availability source precedence | **Union** — either source suffices; record confirming source(s) | F7, §7 |
| D7 | Token cost per MCP call | **Omit from #195 entirely**; revisit on #248 → **Resolved under #262** (not #248): shipped as an explicitly-labelled proxy (M4, `--track-mcp-call-sizes`), not dropped; see issue #262 and PRs #270-#273 | F13, §10 |
| D8 | Session availability rollup across agents | **(a)** Union across agents in the session | F7, §7 |

### Notes carried forward from the resolutions

**D1.** Issue #195's AC bullet "Collection gated behind opt-in flag (default
off)" no longer describes this subcommand and should be edited on the issue —
otherwise the AC reads as unmet at review time. The flag's real home is #248.

**D2 is the largest structural risk in this spec.** Options (a) and (b) added a
flag or a second pass; (c) refactors `parser.py:406-546` in place — the recursion
that carries the depth cap, symlink/junction cycle defense, and three
one-warning-per-session mutable flags, all of which `tests/test_parser.py`
exercises. The extraction is behaviour-preserving by construction (N7), and
Phase 1 gates on `tests/test_parser.py` passing **unchanged** — no edits, no
`xfail`, no re-baselining. If a parser test needs modification to go green, the
extraction changed behaviour and must be reworked, not the test.

**D3.** `--compact` affects `by_agent` only. Default remains #195's specified
shape so the AC is met literally; `--compact` exists because ~50 agents × ~250
tools makes the default dict dominate the payload.

**D6.** The two sources are complementary, not competing: `mcp_instructions_delta`
misses servers that ship no instructions, `deferred_tools_delta` misses eagerly
loaded tools (§2.3). A server named by one and not the other is a blind spot in
the silent one. No removal-precedence rule beyond the in-file-order delta
application already required by F7.

**D8.** Union answers the prune question ("was this server exposed to this
session's work at all?") and is the only option that captures #195's use case 1 —
CodeGraph exposed to sub-agents but not the root. Per-agent grants stay in the
intermediate representation so `--agent` narrows correctly (test T15).

---

## 7. Output schema (revised from issue #195)

Deltas from the issue body are marked ◆.

```json
{
  "window": {
    "start": "2026-08-14",
    "end": "2026-08-21",
    "sessions": 142,
    "sessions_skipped": 3
  },
  "availability_signal": {
    "sessions_with_signal": 138,
    "sessions_without_signal": 4,
    "sources": ["deferred_tools_delta", "mcp_instructions_delta"],
    "by_server_sources": {
      "codegraph": ["deferred_tools_delta", "mcp_instructions_delta"],
      "azure": ["deferred_tools_delta"],
      "github": ["mcp_instructions_delta"]
    }
  },
  "by_tool": {
    "Read": 8421,
    "Grep": 4112,
    "mcp__github__get_pull_request": 188,
    "mcp__codegraph__codegraph_explore": 23
  },
  "by_server": {
    "codegraph": {
      "total_calls": 47,
      "sessions_seen_in": 6,
      "sessions_used_in": 4,
      "avg_calls_per_active_session": 11.75,
      "by_method": { "codegraph_explore": 40, "codegraph_status": 7 }
    },
    "azure": {
      "total_calls": 0,
      "sessions_seen_in": 9,
      "sessions_used_in": 0,
      "avg_calls_per_active_session": null
    },
    "excalidraw": {
      "total_calls": 0,
      "sessions_seen_in": null,
      "sessions_used_in": 0,
      "avg_calls_per_active_session": null
    }
  },
  "by_agent": {
    "general-purpose": { "Read": 5102, "Grep": 2811 },
    "general-purpose→code-writer": { "Read": 1402, "Grep": 988 }
  },
  "compact": false,
  "warnings": {
    "malformed_mcp_names": 0,
    "unreadable_transcripts": 3,
    "workflow_agents_unattributed": true
  }
}
```

◆ `window.sessions_skipped` — F8 needs a visible counter.
◆ `availability_signal` — coverage denominator for `sessions_seen_in` (§2.3).
◆ `sessions_seen_in: null` — signal-absent, distinct from `0` (§2.3). The
  `excalidraw` entry above illustrates the difference from `azure`.
◆ `avg_calls_per_active_session: null` when `sessions_used_in == 0` — the issue
  omits the field entirely in that case; an explicit `null` is easier to consume.
◆ `by_server[*].by_method` — satisfies the AC "`by_tool` breakdown demonstrates
  multi-tool servers showing actual usage subset" without a client-side join,
  and is what #248's expandable-method-detail requirement will need.
◆ `by_agent` keys use `AGENT_PATH_SEPARATOR` (`→`) paths, not bare leaf names —
  matches `aggregator.py:24-40` so keys join against existing dashboard data.
◆ `warnings` — F8/F9 and the §4.3 omission, surfaced rather than silent.

◆ `availability_signal.by_server_sources` — D6 union provenance: which of the two
  complementary signals confirmed each server. A server appearing under only one
  source is expected, not an anomaly (§2.3).
◆ `compact` — echoes the `--compact` flag so a consumer can tell which `by_agent`
  shape it received without inferring from the keys.

`sessions_seen_in` is the **union across agents in the session** (D8 = a).

### `--compact` `by_agent` shape (D3 = c)

`--compact` replaces the `by_agent` block above with:

```json
"by_agent": {
  "general-purpose": { "_builtin": 7913, "github": 188, "codegraph": 23 },
  "general-purpose→code-writer": { "_builtin": 2390, "codegraph": 12 }
},
"compact": true
```

- `_builtin` is the sum of **all** non-MCP tool calls for that agent — a single
  integer, not a nested dict.
- MCP keys are bare server names (post-`normalize_mcp_tool_name`), values are
  call counts for that agent.
- Malformed MCP names (F9) fall into `_builtin` under `--compact`, and are still
  counted in `warnings.malformed_mcp_names`.
- Every other top-level key is byte-identical between the two modes.

`window.sessions` counts sessions **after** `project_exclude_patterns` filtering
(F10), not the raw corpus.

---

## 8. Phasing

Each phase is one PR against `main` from its own worktree
(`.worktrees/<branch>`), per CLAUDE.md § Worktrees.

**Phase 0 — resolver extraction (D5 = b).** Move `_normalize_mcp_tool_name` to
`src/claude_prospector/mcp_names.py` as public `normalize_mcp_tool_name`,
re-export from `session_summary` under the old private name. No behaviour change.
Existing `session_summary` / `session_audit` tests must pass **untouched**.

**Phase 1 — walker extraction (D2 = c), then collection.** Two distinct pieces of
work with a hard gate between them; they may be one PR with two commits, but the
gate is not optional.

- **1a — walker extraction (pure refactor).** New
  `src/claude_prospector/transcript_walker.py` owning the `subagents/` recursion,
  `agent_path` construction, `_sanitize_agent_name`, depth cap, cycle defense,
  and the three one-warning-per-session mutable flags currently in
  `_parse_subagents_recursive` (`parser.py:406-546`). `parser.py` becomes a
  visitor over that walker, producing exactly the `MessageRecord`s it does today.
  **Hard gate: `uv run pytest tests/test_parser.py` passes with `tests/test_parser.py`
  unmodified** — no edits, no `xfail`, no re-baselining. Also run the full suite
  and `uv run ruff check .` + `uv run ruff format --check .` (CLAUDE.md § CI
  gates). Per N7 this is a refactor, not a redesign: do not change the depth cap,
  warning text, `unknown` fallback, or the `workflows/` behaviour.
- **1b — collection visitor.** New `src/claude_prospector/tool_collection.py`,
  the *second* visitor over the walker. Adds `ToolUseRecord` and
  `AgentAvailability` to `models.py` (frozen, slots). Because collection is its
  own visitor it never runs `_parse_jsonl_messages`'s `message.id` dedup guard —
  it reads every assistant line and dedups by `tool_use.id` only, which
  structurally sidesteps the §4.1 hazard. The fragment-line regression test (§9
  T2) locks that in so a future refactor cannot reintroduce it. Ships with no
  CLI surface.
- Perf gate per N5: `dashboard --format json` before/after on the local corpus.

**Phase 2 — aggregation + `tool-usage` CLI.** `compute_mcp_usage(...)` in
`aggregator.py` following the `compute_skill_adoption` shape
(`aggregator.py:241-293`); new `cli/tool_usage.py`; `__main__.py` registration;
`--compact` (D3); README subcommand section (the README has a `## Subcommands`
block at line 221 with one `###` per subcommand — add `### tool-usage` there,
plus the config-validation example the AC requires).

**Phase 3 — dashboard panel. Shipped under #248, not #195 (PRs #259–#261).** New
`by_mcp_usage` field on `AggregateResult`, conditional attach in
`dashboard.py`, new `data` key in `renderer.py`, new `static/views/mcp-usage.js`
read via `_read_static()`, new `.view-toggle` tab in `templates/dashboard.html`.

**Shipped shape, reconciled with this sketch:** the tab landed as a new
top-level view (`data-view="mcp"`, "MCP Usage") beside Overview/Breakdown/
Advanced, not a sub-panel inside the Breakdown view — the sketch above is
directionally correct on that point. `by_mcp_usage` carries `by_tool`,
`by_server`, `availability_signal`, `warnings`, and `window`; `by_agent` and
`compact` are deliberately **omitted** (absent, not `{}`) — the dashboard
payload is written to disk on every run, and none of this spec's own §5
requirements needed a per-agent MCP breakdown on the dashboard surface, so the
extra bytes were not carried through. The exact field-by-field shape and the
rationale for the omission are recorded in PR #261; this spec does not
restate them.

**Scope boundary note:** `AggregateResult` gaining `by_mcp_usage` in Phase 3
changed `dashboard --format json` output only for opted-in consumers. Per D1
that field is gated behind `dashboard --track-mcp-calls` (default off), so
existing JSON consumers were unaffected — the key is omitted entirely, not
emitted as `{}`, when the flag is off.

---

## 9. Test plan

Convention: `tests/unit/test_<cli_module>.py` mirrors
`src/claude_prospector/cli/<module>.py`; `tests/test_<module>.py` mirrors
top-level modules. Fixtures via `_write_jsonl` / `_assistant_line` / `_meta_json`
in `tests/conftest.py`.

| # | Test | Asserts |
| --- | --- | --- |
| T1 | Parent-agent attribution (AC-required) | MCP `tool_use` blocks injected into a `nested_session_dir` variant land under the right `agent_path` key, at depth ≥ 2 |
| T2 | **Fragment-line regression** (§4.1) | Two assistant JSONL lines sharing one `message.id`, each with a distinct `tool_use` block → **both** counted. Guards the `766acba`-class bug in the opposite direction |
| T3 | `tool_use_id` dedup | The same `toolu_` id appearing twice counts once |
| T4 | `tool_result` not counted | A `user` entry echoing `tool_use_id` does not increment `by_tool` |
| T5 | Both MCP naming forms | `mcp__plugin_github_github__create_issue` and `mcp__azure__storage` both roll up correctly (parametrised against `normalize_mcp_tool_name`) |
| T6 | Malformed MCP name | Appears in `by_tool` raw, absent from `by_server`, increments `warnings.malformed_mcp_names` |
| T7 | `sessions_seen_in` null vs zero | Fixture A: transcript with `deferred_tools_delta` listing a never-called server → `0`. Fixture B: transcript with no delta entry → `null` |
| T8 | Delta ordering | `addedNames` then a later `removedNames` for the same tool → not counted as available at end of session |
| T9 | Built-ins counted | `Read` / `Grep` appear in `by_tool` — the explicit `SKIPPED_TOOLS` guard (§3) |
| T10 | Frequency preserved | 10 consecutive identical MCP calls → `10`, not `1` — the `_collapse_consecutive` guard (§3) |
| T11 | Graceful skip | Unreadable + non-JSONL transcripts → run completes, `window.sessions_skipped` incremented |
| T12 | Filters | `--server codegraph` (AC-required), `--agent code-writer` (AC-required), `--tool` glob, `--days` boundary |
| T13 | CLI smoke | `--help`, exit codes, argparse defaults (`--compact` defaults `False`, `--days` defaults `7`), and that **`--track-mcp-calls` is rejected** as an unknown argument (D1 = a). Template: `test_dashboard_no_window_flag_yields_none` (`tests/test_cli_subcommands.py:60-76`) |
| T14 | Exclude-pattern inheritance (F10) | A session whose `project_path` matches `project_exclude_patterns` is absent from output and from `window.sessions` |
| T15 | Per-agent availability divergence (D8 = a) | Root grants server X, sub-agent does not → `sessions_seen_in[X] == 1`; `--agent <sub>` reports X as not-seen for that agent |
| T16 | **Walker parity** (D2 = c, Phase 1a gate) | `tests/test_parser.py` passes with **zero modifications** after the extraction. This is a gate on the existing file, not a new test |
| T17 | Walker visitor isolation (D2 = c) | Driving the walker with a no-op visitor yields the same `agent_path` set as the `parser.py` visitor — depth cap, cycle defense, and `unknown` fallback included (`tests/test_transcript_walker.py`) |
| T18 | `--compact` shape (D3 = c) | Same fixture with and without `--compact`: `by_tool`, `by_server`, `window`, `availability_signal` byte-identical; `by_agent` switches to server keys + `_builtin` integer; `compact` field echoes the flag |
| T19 | Union availability sources (D6) | Server named only by `mcp_instructions_delta` and server named only by `deferred_tools_delta` are both available; `availability_signal.by_server_sources` records which source(s) confirmed each |

---

## 10. Out of scope

- **`workflows/wf_*/` agent attribution (§4.3).** Pre-existing parser gap
  affecting token attribution too. **Action: file a sibling issue** — "parser:
  `subagents/workflows/wf_*/` agents are not traversed, messages missing from all
  output". Reference this spec §4.3 for the evidence.
- **Dashboard panel** — #248, Phase 3.
- **Runtime instrumentation / hooks** — #241, closed as not planned.
- **Token cost per tool call** — D7 = omit from #195; **resolved under #262**
  (not #248) as an explicitly-labelled proxy (M4, `--track-mcp-call-sizes`;
  PRs #270, #271, #272), not dropped.
- **Fixing the `workflows/` gap while extracting the walker** — N7. The walker
  extraction preserves today's behaviour, including this omission. The fix is the
  sibling issue's job.
- **`tool_use.input` payload analysis** — N6.
- **Cross-referencing `settings.json`** — unnecessary (§2) and wrong (it reflects
  read-time config, not session-time).
- **A skill front-end.** This repo's established pattern is deterministic CLI +
  skill front-end — `drift-aggregation.md:9` lists
  `skills/session-analysis/SKILL.md` in its `touches:`, and README lists five
  shipped skills (`README.md:52-108`). #195's use cases (config-change
  validation, server triage, agent-discipline auditing) are skill-shaped, but
  none of its ACs require a skill, and the JSON contract is the stated
  deliverable. **Decision: no skill surface in v1** — revisit once the JSON
  shape has settled and #248's dashboard panel exists. Recorded explicitly so a
  reviewer sees a choice rather than an omission.

---

## 11. Sources

**Repo (verified by read, 2026-08-21, `main` @ `ad1f3b9`):**
`src/claude_prospector/cli/session_summary.py:23-26,33-43,227-272,275-365,368-391,394-424`;
`src/claude_prospector/parser.py:322-379,340-347,353-360,406-546,507,532,552-654`;
`src/claude_prospector/aggregator.py:24-40,43-57,74-238,241-293`;
`src/claude_prospector/models.py:9-38`;
`src/claude_prospector/__main__.py:8-16,40-46,54-73`;
`src/claude_prospector/parser.py:657-710` (`parse_sessions`, incl.
`project_exclude_patterns` at `:667-670,702-703`);
`src/claude_prospector/cli/dashboard.py:19-61,77-80,142-224`;
`README.md:52-108` (shipped skills), `README.md:221` (`## Subcommands`);
`docs/superpowers/specs/drift-aggregation.md:1-13` (spec frontmatter +
CLI/skill-split precedent);
`CLAUDE.md` § CI gates, § Repo layout.

**Repo (from the router's Explore map — cited but not independently re-read):**
`src/claude_prospector/renderer.py:51-130,87-98`;
`src/claude_prospector/templates/dashboard.html:42-83`;
`src/claude_prospector/cli/dashboard.py:170-179`;
`tests/test_cli_subcommands.py:60-76`; `tests/conftest.py`.

**Git:** commit `ad1f3b9` (`--redact-prompts`), commit `766acba` (`dedup
assistant messages by message.id to stop token-usage inflation`) — both from the
session-start `git log`.

**GitHub (fetched 2026-08-21 via the public issue pages; `gh` and the GitHub MCP
were both unavailable in this session, so state was read from rendered HTML
rather than the API):** issue #195 (open), issue #248 (open, filed 2026-08-08),
issue #241 (closed as not planned).

**Empirical transcript probes (2026-08-21, Claude Code `2.1.225`, local
`~/.claude/projects/**`, user-local and rotating — re-run rather than trust):**
probes P1–P6, §2.1. Findings in §2.2, §4.1, §4.3.
