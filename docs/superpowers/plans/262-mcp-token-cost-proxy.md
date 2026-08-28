---
title: Token cost proxy per MCP tool call (issue #262, D7)
touches:
  - src/claude_prospector/models.py
  - src/claude_prospector/tool_collection.py
  - src/claude_prospector/aggregator.py
  - src/claude_prospector/cli/dashboard.py
  - src/claude_prospector/static/views/mcp-usage.js
  - README.md
  - docs/superpowers/specs/mcp-tool-usage-analyzer.md
  - tests/test_dashboard_mcp_usage.py
  - tests/test_mcp_usage_view.py
  - tests/unit/test_tool_collection.py
  - tests/test_aggregator_tool_usage.py
skills_relevant:
  - python
  - simplicity-first
---

# Token cost proxy per MCP tool call — issue #262

**Status: Decisions resolved — ready for Phase 1.** §8 Phase 0's measurement
gate has run; its findings were posted as a GitHub comment on issue #262
(throwaway script, not committed, per §8's own instructions). Both blocking
decisions in §7 are resolved: **D-1 → M4** (result-payload-size metric) and
**D-4 → yes-isolated-with-secondary-flag** (a documented new variant, not one
of the three options originally listed). D-2 and D-3 are now moot — see §7.

Issue #262 asks for a token-cost proxy per MCP tool call, deferred here from
#248 as decision D7 of the MCP tool-usage spec
(`docs/superpowers/specs/mcp-tool-usage-analyzer.md:509`). That spec's F13
requires the eventual metric ship "as an explicitly-labelled proxy or be
dropped" (`mcp-tool-usage-analyzer.md:464-465`), and §10 repeats the same
either/or (`mcp-tool-usage-analyzer.md:758-759`). **"Drop it" is a
pre-authorised outcome of this plan, not a failure mode.**

---

## 1. Verified starting state

Every claim in this section was read from source during planning.

| Fact | Source |
| --- | --- |
| `ToolUseRecord` has exactly four fields — `tool_name`, `tool_use_id`, `agent_type`, `agent_path`. No token fields, no `message_id`. | `src/claude_prospector/models.py:135-152` |
| `MessageRecord` carries the four usage fields and a `total_tokens` property summing all four. | `src/claude_prospector/models.py:9-47` |
| Token usage is only ever read at **message** level, off `entry["message"]["usage"]`, and only for `entry["type"] == "assistant"`. | `src/claude_prospector/parser.py:334-341, 364-367` |
| Fragment lines sharing one `message.id` are collapsed to a single `MessageRecord`; the comment states summing duplicates "would multiply every usage field". | `src/claude_prospector/parser.py:345-354, 371-372` |
| `collect_unit`'s `assistant` branch reads `message["content"]` and iterates `tool_use` blocks, but never touches `message["usage"]` or `message["id"]`. | `src/claude_prospector/tool_collection.py:122-146` |
| `collect_unit` de-dups by `tool_use.id` only; a block whose `id` is missing/empty is emitted **without** being added to `seen_ids`, so it can never be de-duped. | `src/claude_prospector/tool_collection.py:134-138` |
| `tool_collection`'s module contract is explicitly "raw counts only — no filtering, no normalisation, no aggregation. Those belong to a downstream aggregator." | `src/claude_prospector/tool_collection.py:4-6` |
| `_iter_entries` `json.loads` **every** line of the transcript, including `user` entries, and yields any dict. Non-`assistant`/`attachment` entries are parsed and then discarded. | `src/claude_prospector/tool_collection.py:31-56, 122-124` |
| `compute_tool_usage` builds `by_tool` / `by_server` / `by_agent` from `Counter[str]` only. No token value is read anywhere in the function. | `src/claude_prospector/aggregator.py:335-426` |
| Token aggregation is a disjoint pipeline: it runs in `aggregate()` off `MessageRecord`, never sees a `ToolUseRecord`. | `src/claude_prospector/aggregator.py:64-75` (`_add_tokens`), `:304-426` (`compute_tool_usage`) |
| The dashboard drops `by_agent` and attaches `window` before publishing `by_mcp_usage`. | `src/claude_prospector/cli/dashboard.py:202-220` |
| `--track-mcp-calls` is opt-in, default off, and its help text already frames it as an IO-cost tradeoff. | `src/claude_prospector/cli/dashboard.py:139-148` |
| Measured cost of the flag on the maintainer's corpus: 4.62s off vs 9.61s on (~2.08x). | `README.md:254-258` |
| A `tool_use`'s matching `tool_result` appears on the **following `user` entry**, carrying the same `tool_use_id`. | `docs/superpowers/specs/mcp-tool-usage-analyzer.md:269, 299-304` |
| Parallel tool calls in one assistant turn are written as consecutive JSONL lines sharing one `message.id`, each holding a distinct `tool_use` block. | `docs/superpowers/specs/mcp-tool-usage-analyzer.md:265-273` |
| The shipped panel renders `total_calls`, `sessions_seen_in`, `sessions_used_in`, `avg_calls_per_active_session`, and a `by_method` list per server card. | `src/claude_prospector/static/views/mcp-usage.js:240-275, 289-323` |

Two facts came from the pre-run `Explore` pass recorded in the dispatch brief
and were **not** independently re-verified this session (no shell available —
see §8 Phase 0): (a) a rarer shape where one JSONL line's `content` array holds
≥2 `tool_use` blocks under a single `usage` object; (b) `usage.iterations`
exists in the raw format but carries no sub-message granularity. Neither is
load-bearing for the design in §5 — the denominator scheme there handles both
line shapes uniformly, because it groups **emitted records**, not lines.

One structural probe was run this session against real transcripts under
`C:\Users\chris\.claude\projects` (matched-substring output only, no payloads
read into the transcript): `tool_result` blocks carry
`"tool_use_id":"toolu_..."` alongside a `"content"` field that is **either a
plain JSON string or a list of blocks** — both shapes occur in the wild.

---

## 2. The finding that reframes the issue

Issue #262's own framing guesses at "input+output tokens attributable to the
surrounding assistant turn". That guess is implementable, but it does not
measure what an MCP call actually costs, for a structural reason:

**A tool's result payload is never priced on the message that made the call.**
The `tool_result` lands on the following `user` entry
(`mcp-tool-usage-analyzer.md:269, 299-304`), and `user` entries carry no
`usage` — the parser only reads usage from `assistant` entries
(`parser.py:334`). The result's tokens are billed as prompt-side input on the
**next** assistant request, folded together with everything else injected in
between.

So the calling message's `usage` mostly reflects *the conversation so far*
(`input_tokens` + `cache_read_input_tokens` are whole-prompt snapshots, not
increments) plus the model's own output for that turn. A `codegraph_explore`
returning 20k tokens and a `get_issue` returning 200 tokens produce
**identical** usage on their calling messages if they are called at the same
point in a conversation. The metric would rank MCP servers by *when in a
session they tend to be called*, not by what they cost.

This does not make the calling-message metric worthless — see M1 below — but it
means the intuitive reading of the resulting number would be wrong, which is
precisely the risk F13's labelling requirement exists to contain.

---

## 3. Metric options

Four candidates. D-1 (§7) picks one.

### M1 — Billed cost of the issuing request, split across its tool calls

Attribute the calling assistant message's `usage` to the `tool_use` blocks in
that message.

- **Honest name:** "billed tokens of the request that emitted this call".
- **Pro:** matches billing reality — you are charged per request, so summing
  request costs is a real quantity. Zero new IO. Implementable today.
- **Con:** dominated by conversation size, not by the tool. Systematically
  over-prices tools called late in long sessions. Cross-message sums balloon far
  past session totals because `input_tokens` and `cache_read_tokens` repeat the
  whole prompt every turn — a reader comparing this against the dashboard's
  session token totals will see numbers that do not reconcile.
- **Con:** requires the even-split-vs-replicate decision (D-2) and has no ground
  truth for it.

### M2 — Context-growth delta after the call

`(next assistant message's input+cache totals) − (this message's)`, split across
the calls in between.

- **Pro:** conceptually closest to "what did this call add to my context".
- **Con:** **unverified and possibly unusable.** The delta absorbs everything
  injected between the two assistant turns — user text, system reminders, hook
  output, attachments, and *all* results from a parallel batch — not just the
  one tool result. `cache_read_input_tokens` also swings discontinuously at
  cache hit/miss boundaries, which are unrelated to tool cost.
- **Verdict:** do not adopt without the Phase 0 measurement (§8). If the
  no-tool-call control transitions show a noise floor comparable to the signal,
  M2 is dead.

### M3 — Drop the metric (pre-authorised by F13)

Ship nothing token-shaped; close #262 recording *why*, and keep the panel's
call-volume framing.

- **Pro:** the spec explicitly permits this
  (`mcp-tool-usage-analyzer.md:464-465, 758-759`). A confidently wrong number on
  a dashboard is worse than an absent one.
- **Con:** the underlying question ("which MCP server is eating my context?")
  stays unanswered.

### M4 — `tool_result` payload size, joined by `tool_use_id` **(recommended, pending Phase 0)**

Measure the size of each call's own `tool_result` content and convert to an
estimated token count.

This is materially better than M1/M2 on four axes, all of which follow from
facts verified in §1:

1. **Exact per-call attribution, no splitting.** The `tool_result` carries the
   `tool_use_id` (`mcp-tool-usage-analyzer.md:269`), and `ToolUseRecord` already
   has a `tool_use_id` field (`models.py:150`) that nothing currently
   cross-references. The join key already exists; D-2 (even-split vs replicate)
   evaporates entirely.
2. **Zero extra IO, and zero extra parsing.** Both the `tool_use` and its
   `tool_result` live in the same transcript file already scanned once by
   `collect_unit`, and `_iter_entries` already `json.loads` every `user` line
   and throws it away (`tool_collection.py:31-56, 122-124`). This satisfies the
   brief's cost-discipline constraint (`README.md:254-258`) outright.
3. **It measures the thing people actually want.** The result payload *is* the
   context an MCP call consumes. It is what makes `codegraph_explore` expensive
   and `get_issue` cheap.
4. **It is inherently a proxy**, so F13's labelling requirement is satisfied by
   construction rather than by disclaimer: characters-to-tokens is an estimate
   (no tokenizer ships with this repo, and adding one would violate the spec's
   N2 "no new runtime dependency", `mcp-tool-usage-analyzer.md:470`).

**Open risks specific to M4, all of which Phase 0 must clear:**

- **Content shape.** Confirmed to be string-or-list. The list form's blocks need
  a size rule, and **image blocks must be excluded or handled separately** — a
  base64 image would overstate a call's cost by orders of magnitude. But
  excluding them must not make such a call look *cheap*: an image-returning MCP
  call is expensive, and reporting it as a near-zero number is more wrong than
  reporting nothing. A call whose result contains an excluded block must render
  as `unknown`, not as a small number — the same null-vs-zero discipline the view
  already enforces for `sessions_seen_in` (F6, `mcp-usage.js:26-33`).
- **Fidelity.** Whether the stored `tool_result` is byte-identical to what the
  model received (vs. truncated, re-serialised, or supplemented by Claude Code's
  `toolUseResult` sidecar field) is **unverified**. If the transcript stores a
  truncated copy, M4 systematically under-reports.
- **Privacy.** The module docstring states `tool_use.input` is never touched
  because it carries file paths and shell commands
  (`tool_collection.py:8-9`), and spec N6 restricts output to names and counts
  (`mcp-tool-usage-analyzer.md:488-491`). M4 reads result payload **length**
  and never emits payload text — compatible with N6's intent, but it is an
  extension of the current privacy posture and needs explicit sign-off (D-4).
  Note M4 deliberately does **not** measure the input/argument side, since that
  would require touching `tool_use.input` in violation of N6.
- **Ratio calibration.** ~4 chars/token is the usual English rule of thumb, but
  MCP results are overwhelmingly JSON and code, which tokenize denser. Phase 0
  should calibrate rather than assume.

---

## 4. What is *not* needed

The issue asks whether `ToolUseRecord` needs a `message_id` to enable a join
against `MessageRecord`. **No — and no cross-pipeline join is needed at all.**

`collect_unit` already holds the whole `entry["message"]` dict in scope
(`tool_collection.py:125-146`); `usage` and `id` are free reads on an object it
has already parsed. Under M4 they are not even required. Reaching across to the
`MessageRecord` pipeline would mean adding a correlator to two record types and
joining two passes that are deliberately disjoint (`aggregator.py:64-75` vs
`:304-426`) — all to obtain data that is already local.

---

## 5. Data-model design (resolved — applies only if D-1 lands on M1 or M2)

Under M4 this section is unnecessary; it is retained because M1/M2 both need it.

The naive approach — emit a pre-divided share from `collect_unit` — does not
work. In the fragment-line shape the number of blocks in a message is not known
until every line sharing that `message.id` has been read
(`mcp-tool-usage-analyzer.md:265-273`), so the forward scan cannot compute a
share as it goes. The opposite naive approach — carry `message_id` on the record
and group in the aggregator — introduces a dependency on `message.id` being
globally unique across the whole corpus, which is unverified and unnecessary.

**Design:** after `collect_unit`'s scan completes, group the **emitted records**
by their message id and stamp each with:

- `message_id: str` — `""` when absent.
- `share_denominator: int` — the count of records emitted for that message id.
- the message's four usage values (or their sum).

Three properties make this correct:

- **It groups emitted records, not blocks.** This matters because of the de-dup
  asymmetry at `tool_collection.py:134-138`: a block with a duplicate `id` is
  skipped, and a block with a missing `id` is emitted but never registered in
  `seen_ids`. Counting blocks-seen would produce shares that do not sum to the
  message total; counting records-emitted always does.
- **It is line-shape agnostic.** Fragment lines and multi-block lines both
  resolve to "records emitted under one message id", so the unverified
  multi-block observation from the Explore pass cannot break it.
- **The denominator is a fact; the division is a policy.** Collection emits the
  fact, `compute_tool_usage` applies the policy (divide by it, or ignore it and
  replicate). This preserves `tool_collection.py:4-6`'s stated contract.

**Missing `message.id`.** When `msg.get("id")` is `None`, the record cannot be
grouped. Follow the existing precedent of counting rather than silently
guessing: exclude those records from the cost metric and increment a new
`warnings.uncorrelated_tool_calls`, mirroring how `warnings.malformed_mcp_names`
is handled (`aggregator.py:373-374, 423-425`).

---

## 6. Output surfacing (dischargeable regardless of D-1)

F13 requires the metric be "explicitly-labelled as a proxy"
(`mcp-tool-usage-analyzer.md:464-465`). Three mechanisms, all additive to the
shipped `by_mcp_usage` shape (`cli/dashboard.py:202-220`) rather than replacing
it:

**a. Key naming carries the caveat.** Never `tokens`. Use
`estimated_result_tokens` (M4) or `estimated_request_tokens` (M1). A key named
`tokens` will be read as measured no matter what the docs say.

**b. A machine-readable `cost_attribution` block** as a sibling of
`availability_signal`, so a JSON consumer cannot get the numbers without the
method:

```json
"cost_attribution": {
  "method": "tool_result_payload_size",
  "is_proxy": true,
  "unit": "estimated_tokens",
  "basis": "len(tool_result content) / chars_per_token",
  "chars_per_token": 4.0,
  "excludes": ["tool_use.input arguments", "image content blocks"],
  "calls_with_result": 0,
  "calls_without_result": 0,
  "calls_with_excluded_content": 0
}
```

Neither counter is optional. `calls_without_result` covers a call whose result
was never found (truncated transcript, session ended mid-call);
`calls_with_excluded_content` covers a call whose result held an image or other
unmeasurable block. Both must be visibly excluded and rendered as `unknown`
rather than silently counted as zero-cost — a zero here is a claim that the call
was free, which for an image-returning call is the opposite of the truth.

**c. UI.** A fourth stat on each server card
(`static/views/mcp-usage.js:240-275`), labelled `Est. result tokens` — the
"Est." prefix inside the label itself, not only in a footnote. The existing
`.blind-spot` note pattern (`mcp-usage.js:216-223`) is the right place for the
one-sentence method statement. Reuse `formatCountOrUnknown`
(`mcp-usage.js:30-33`) so "no result data" renders as `unknown`, not `0` — that
null-vs-zero distinction is already load-bearing in this view (F6).

---

## 7. Decisions — resolved 2026-08-27

Both blocking decisions have been made by the repo owner in conversation,
following Phase 0's measurement findings (posted as a GitHub comment on issue
#262). D-2 and D-3 were scoped as conditional on D-1 and are now moot.

| # | Question | Options | Notes |
| --- | --- | --- | --- |
| **D-1** | Which metric? | **M1** issuing-request cost · **M2** context-growth delta · **M3** drop · **M4** result-payload size (adopted) | **RESOLVED → M4.** See "D-1 resolution" below. |
| **D-2** | Even-split or replicate across parallel calls in one message? | even-split · replicate-full · exclude multi-call messages | **N/A — moot.** Only applied if D-1 = M1 or M2; D-1 resolved to M4, which needs no split (§3 M4 point 1). |
| **D-3** | Which token fields constitute "cost"? | `output` only · `input+output` · all four | **N/A — moot.** Only applied if D-1 = M1 or M2; same reason as D-2. |
| **D-4** | Is reading `tool_result` payload **length** (never content) an acceptable extension of the privacy posture in `tool_collection.py:8-9` / spec N6? | yes · yes-with-a-cap · no · **yes-isolated-with-secondary-flag (adopted)** | **RESOLVED → yes-isolated-with-secondary-flag.** A new, documented amendment to this options list — not simply "yes". See "D-4 resolution" below. |

### D-1 resolution — M4

M4 was strong on both viability and fidelity in the Phase 0 measurement (issue
#262, Phase 0 findings comment): 0 of 2,882 MCP `tool_use` ids were missing a
matching `tool_result`; the result-size distribution differentiated
meaningfully by server and method; 0 image blocks appeared in the sample; the
truncation rate was ~0.85%. Fidelity checked out too — across n=330 pairs, the
median absolute difference between `tool_result` and `toolUseResult` sidecar
sizes was 0 chars.

By contrast, Phase 0 item 5 measured Pearson r=0.37 between calling-message
context total and turn index within the session — a real positional
component, reported per item 5's "report it either way so D-1 is decided on
numbers" instruction. That is well below item 5's own "near 1" bar for a
clean confound, but the repo owner read it, together with M4's clean win on
viability and fidelity, as sufficient corroboration of §2's structural
argument to not pursue M1 further. M2 turned out to be practically
uncalibratable: Phase 0 item 3 found
zero transitions across ~58k assistant turns that met the plan's "clean
transition" bar, because Claude Code's system-reminder injection makes an
isolated tool-call transition effectively nonexistent in this transcript
format — which also makes Phase 0 item 4's kill-or-cure control comparison
moot, since there was no clean-transition signal to compare against a
control. M3 (drop) remains pre-authorised by F13 but is no longer needed,
since M4 is viable.

### D-4 resolution — yes-isolated-with-secondary-flag

Reading `tool_result` payload **length** (a number; never the content itself)
is an acceptable extension of the privacy posture in `tool_collection.py:8-9`
/ spec N6 — but only under two conditions the repo owner set:

1. **Code isolation.** The length-reading logic must live in its own
   separate function/module, not folded into `collect_unit`'s existing scan —
   so `tool_collection.py`'s existing privacy claim ("only tool names and ids
   are read; `tool_use.input` is never touched") stays literally true for the
   base scan path, and the new read is a small, separately auditable unit.
2. **Separate opt-in flag.** The read must be gated behind a **new**
   secondary CLI flag on `dashboard`, distinct from the existing
   `--track-mcp-calls` flag (which stays call-counts-only — no result-length
   reads, no change to its existing behavior or help text). Users can run the
   base call-count-only version, or opt further into the new flag knowing it
   will temporarily read privacy-sensitive `tool_result` payload data (length
   only, computed and discarded — never persisted or logged as content) to
   compute the cost-proxy metric. The new flag's help text, and any README
   documentation added later, must state this in plain language — it is a
   privacy-posture change, not just a performance one, and needs its own
   clear disclosure separate from the existing flag's IO-cost framing.

The new flag's exact name is **TBD** — Phase 1 must name it.
`--track-mcp-call-sizes` is a reasonable illustrative suggestion, not a
decision.

Two things the planner does **not** need answered: whether `ToolUseRecord` needs
a `message_id` (§4 — no join needed) and how the denominator should be computed
(§5 — resolved).

---

## 8. Phased implementation

### Phase 0 — Measurement gate (throwaway script, no PR)

**Purpose: produce the evidence that answers D-1.** This plan deliberately does
not recommend M1 or M2 on reasoning alone; the required measurements could not
be taken during planning because no shell was available in the planning session.
Precedent for gating on a measured run: spec N5 makes a before/after `dashboard`
timing run a Phase 1 merge gate (`mcp-tool-usage-analyzer.md:478-482`).

Write a scratch script (scratchpad, not the repo) over the local corpus that
reports:

1. **M4 viability.** Distribution of `tool_result` content sizes per MCP
   server/method. Confirm both content shapes parse. Count how many `tool_use`
   ids have **no** matching `tool_result` in the same file. Detect image blocks
   and report what fraction of payload bytes they represent.
2. **M4 fidelity.** Check whether a `toolUseResult` sidecar field exists on the
   same `user` entry, and whether it disagrees in size with the `tool_result`
   block. Look for truncation markers.
3. **Chars-per-token calibration.** Compare result-payload chars against the
   next assistant message's `input_tokens` growth to sanity-check the divisor —
   but **only on clean transitions**: exactly one intervening `tool_use`, and no
   other injected content between the two assistant turns (no user text, system
   reminders, hook output, or attachments). That growth figure is the same
   confounded delta item 4 exists to interrogate; calibrating on unfiltered
   transitions would tune the divisor against noise while appearing to satisfy
   this item. Report a ratio range and the number of clean transitions the range
   is based on — if too few exist to be meaningful, say so rather than
   extrapolating.
4. **M2 noise floor (kill-or-cure).** Compute the `(next ctx − this ctx)` delta
   for assistant→assistant transitions **with** an intervening tool call and,
   as a control, **without** one. If the control's distribution overlaps the
   treatment's, M2 is dead — record that and drop it.
5. **M1 confound check.** Correlate calling-message context total against
   message index within the session. A correlation near 1 confirms M1 measures
   conversation position; report it either way so D-1 is decided on numbers.

**Exit criterion:** a short findings comment on issue #262 with those five
results. **Then re-open D-1 with the repo owner.** Do not proceed to Phase 1
until D-1 and D-4 are answered.

**Status: complete.** Findings posted as a GitHub comment on issue #262; D-1
and D-4 are resolved in §7.

### Phase 1 — Collection (TDD)

Scope is now fixed by D-1 = M4 (§7). The M1/M2 branch below is retained as
decision history, per this plan's citation/decision-log conventions, rather
than deleted — it explains why §5's `message_id`/`share_denominator` scheme is
not being built.

- **M4 (live — the only branch that ships):** extend `collect_unit`'s scan
  with a `user` branch that records `{tool_use_id: result_size}` for
  `tool_result` blocks, and stamp each `ToolUseRecord` with
  `result_chars: int | None` (`None` = no result found, distinct from `0`).
  No new file reads; the `user` entries are already parsed and discarded
  (`tool_collection.py:31-56`).

  **D-4's two conditions (§7) apply to this branch:**
  - **Code isolation.** The length-reading logic must live in its own
    separate function/module, called from — not folded into — `collect_unit`'s
    existing scan, so `tool_collection.py`'s existing privacy claim ("only
    tool names and ids are read; `tool_use.input` is never touched",
    `tool_collection.py:8-9`) stays literally true for the base scan path,
    and the new read is a small, separately auditable unit.
  - **Secondary flag gating.** This branch must be gated behind a **new**
    CLI flag on `dashboard`, distinct from the existing `--track-mcp-calls`
    flag (which stays call-counts-only — no result-length reads, no change to
    its existing behavior or help text). The new flag's exact name is
    **TBD** (Phase 1 must name it; `--track-mcp-call-sizes` is an
    illustrative suggestion only, not a decision). Its help text — and any
    README documentation added in Phase 4 — must plainly disclose that
    enabling it reads `tool_result` payload length (never content, never
    persisted or logged) to compute the cost-proxy metric. This is a
    privacy-posture disclosure, distinct from `--track-mcp-calls`'s existing
    IO-cost framing.

- **M1/M2 (moot — kept as decision history, not implemented):** would have
  implemented §5 — `message_id`, `share_denominator`, and the usage fields on
  `ToolUseRecord`, stamped in a post-scan grouping pass. Phase 0 ruled out
  both metrics (§7 D-1 resolution); this branch does not ship.

Either way: **`ToolUseRecord` is a frozen slotted dataclass**
(`models.py:135`). New fields must be defaulted so existing construction sites
keep working. Confirm the full suite is green with no test edits before adding
new ones; if existing tests must change, that is a signal the field was added
non-additively.

**One known test ripple under M4.** `tests/test_aggregator_tool_usage.py:36-38`
is the only place in `tests/` that constructs a `ToolUseRecord` directly, via a
`_use()` helper that hardcodes `tool_use_id=""` with the docstring "irrelevant
to aggregation" (`:33-34`). M4 makes `tool_use_id` the join key, so that helper
and its docstring must change and those tests need real ids. This is an expected
consequence of the design, not the non-additive signal described above — call it
out in the PR body so it is not mistaken for one.

Tests to add: result-missing → `None` not `0`; string vs list content shapes;
image block excluded; duplicate `tool_use_id` counted once (guards the existing
de-dup at `:134-138`); `tool_result` on a `user` entry does **not** create a new
`ToolUseRecord` (guards spec T4, `mcp-tool-usage-analyzer.md:731`).

### Phase 2 — Aggregation

Add the cost rollup to `compute_tool_usage` (`aggregator.py:304-426`):
per-server and per-method `estimated_result_tokens`, plus the
`cost_attribution` block from §6b. **`by_method` is currently a bare
`dict[str, int]`** (`aggregator.py:408`) and the view iterates it as
`[method, count]` pairs (`mcp-usage.js:230-237`) — adding a second per-method
number is a **breaking shape change** to both. Decide explicitly whether to
widen `by_method` values to objects (and update the view in the same PR) or add
a parallel `by_method_tokens` map. The parallel map is the lower-risk choice and
matches how `window` was bolted on additively (`cli/dashboard.py:214-219`).

Report a **median or mean per call** alongside any total. A total alone invites
the cross-comparison failure described in M1's cons.

### Phase 3 — Dashboard JSON + view

Wire through `cli/dashboard.py:202-220`. **Amended by the D-4 resolution
(§7):** this phase's text originally read "do not add a second flag" — that no
longer holds. `result_chars` collection (Phase 1) is gated behind the new
secondary flag named there (TBD, illustratively `--track-mcp-call-sizes`);
this phase's `cost_attribution`/`estimated_result_tokens` output must be
conditioned on *that* flag, not on `--track-mcp-calls` alone. Then wire the
server-card stat and method note in `static/views/mcp-usage.js` per §6c.
Keep the empty-state path working: `by_mcp_usage` is `{}` when the flag is off
(`mcp-usage.js:302-307`).

### Phase 4 — Docs

Update `README.md:250-261` with the new field and its proxy framing, and amend
`docs/superpowers/specs/mcp-tool-usage-analyzer.md` F13 / §10 to record that D7
was resolved here and how — the spec currently says "revisit on #248"
(`:509, :758-759`), which is now stale in two ways (it resolved to #262, and it
has an answer).

---

## 9. Out of scope

- **Input/argument-side cost.** Measuring `tool_use.input` size violates spec N6
  and the module's own privacy contract (`tool_collection.py:8-9`). Excluded,
  and named in `cost_attribution.excludes` so the omission is visible.
- **A real tokenizer.** Spec N2 forbids a new runtime dependency
  (`mcp-tool-usage-analyzer.md:470`). The metric stays an estimate; this is a
  feature given F13, not a shortfall.
- **Per-call rows in the UI.** The panel is a server/method rollup
  (`mcp-usage.js:277-286`); per-call listing is a different feature and would
  re-raise the payload-privacy question.
- **The `track_mcp_calls` Stop-hook userConfig toggle (#257).** Separate
  workstream, in flight; it governs *whether* collection runs, not *what* is
  collected.
- **Cost attribution for non-MCP (built-in) tools.** The same mechanism would
  work, but #262 is scoped to MCP and the panel only renders `by_server`.
  Record as a follow-up if the metric proves useful.

## 10. Risks

| Risk | Mitigation |
| --- | --- |
| A proxy number is read as measured cost and drives a wrong config decision. | §6 — key naming, machine-readable `cost_attribution`, "Est." in the UI label. This is F13's actual requirement, not decoration. |
| M4 under-reports because transcripts store truncated results. | Phase 0 item 2 is a hard gate; if fidelity fails, fall back to M3. **Cleared by Phase 0** — n=330 pairs, median absolute diff 0 chars; see §7 D-1 resolution. |
| `by_method` shape change breaks the shipped view. | Phase 2 — prefer the additive parallel map; both `tests/test_mcp_usage_view.py` and `tests/test_dashboard_mcp_usage.py` must be updated in the same PR. |
| New `ToolUseRecord` fields break existing fixtures. | Phase 1 — defaulted fields only; full suite green before new tests are added. |
| Implementation starts before D-1 is answered and builds the wrong metric. | **Discharged** — D-1 and D-4 are resolved (§7); this document's status line no longer reads "NOT READY TO IMPLEMENT". |
