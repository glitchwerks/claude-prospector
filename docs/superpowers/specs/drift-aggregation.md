---
title: Drift-aggregation CLI (drift-report) + session-analysis trend front-end
touches:
  - src/claude_prospector/cli/drift_report.py
  - src/claude_prospector/__main__.py
  - src/claude_prospector/cli/variance_save.py
  - tests/unit/test_drift_report.py
  - tests/unit/test_variance_save.py
  - skills/session-analysis/SKILL.md
  - README.md
skills_relevant:
  - python
---

# Drift-aggregation CLI (`drift-report`) — Implementation Spec

Remaining open work on **issue #63** (state: open, pivoted 2026-06-02). The
deterministic 1a `session-audit` CLI and the interpretive 1b `session-analysis`
skill are done (1a merged; 1b merged as PR #213, commit `80cce27`). This spec
covers the third and final component: a **deterministic aggregation CLI** that
reads the accumulated `variance/<id>.json` records and reports drift frequency,
severity distribution, and trend over a configurable time window, plus the
`session-analysis` skill extension that renders the aggregate view in-session.

## 1. Overview

`drift-report` is a new argparse subcommand that scans
`<base_dir>/variance/*.json` (the records the 1b skill persists via
`variance-save`), filters by a configurable time window, and computes:

- **drift frequency** — count and fraction of records classified as drifted
  (severity-primary rule, §5),
- **severity distribution** — histogram across the 0–3 scale plus a `null`
  bucket,
- **trend** — the same two metrics bucketed by day across the window, so a
  caller can see whether drift is rising or falling.

No LLM at aggregation time (locked decision 1). The CLI is the deterministic
engine; the `session-analysis` skill is the in-session front-end that calls it
and renders a human-readable trend summary — the same 1a/1b split pattern already
established (`skills/session-analysis/SKILL.md:26-32`).

This ships as a **separate follow-up on a fresh branch off `main` after PR #213
merges** (locked decision 2). PR #213 is already merged (commit `80cce27`).
The branch for this work is `63-drift-aggregation`, cut from `main` at that
commit. The `variance-save`, `session-analysis`, and `variance/<id>.json` schema
are all present on `main`. The `timestamp` producer field (§2) ships first as
Phase 0 (a small producer PR against merged `main`) before any aggregation code
is written.

### Why this is required

The feature is required by `glitchwerks/claude-configs#535` Phase 5 for
auto-mode `soft_deny` drift rules (issue #63 body, fetched 2026-06-02) — that
consumer needs a machine-readable drift frequency/severity signal, which is why
the CLI emits JSON as its primary contract.

## 2. The `timestamp` field — design and producer placement

A "configurable time window" needs a per-record time anchor. The current
`variance/<id>.json` schema has **no timestamp field** (schema:
`variance_save.py:37-48`). Option (b) — add a `timestamp` field to the
producer's output, derived from the session transcript, with an mtime fallback
for legacy records — is the locked choice.

### Why (b), and why it is cheap here

The producer already has the data. `save_variance_record`
(`variance_save.py:184-258`) reads the full transcript via `read_transcript` at
`variance_save.py:240` and immediately passes the resulting `entries` to
`audit_session`. The raw `entries` are available in that same call frame and
can be inspected for timestamps before `combine_variance` is called.

`read_transcript` is imported from `session_summary` (`variance_save.py:87`) and
returns **raw `json.loads` dicts** (`session_summary.py:519-557`) — NOT the
normalized `Message` objects that `parser.py` builds. The raw entry dicts
contain whatever fields the JSONL line carried. Many JSONL lines carry a
top-level `"timestamp"` key; others (summary lines, meta entries, tool-result
envelopes) do not.

The record gains one field:

```json
"timestamp": "<ISO-8601 UTC, earliest transcript entry time, or null>"
```

### Correct derivation in `save_variance_record`

Compute the earliest timestamp from the raw entry dicts **in `save_variance_record`**
(`variance_save.py:239-258`), where `entries` is in scope. Do not attempt to
derive it inside `combine_variance` (`variance_save.py:129-161`) — that is a
pure function whose signature is `(session_id, audit, judgment)` and it never
receives the transcript entries.

Derivation steps in `save_variance_record` (after `entries` is obtained at L240
and before or after `combine_variance` is called):

1. Filter `entries` to those carrying a top-level `"timestamp"` key:
   `ts_candidates = [e["timestamp"] for e in entries if "timestamp" in e]`
2. If `ts_candidates` is non-empty, normalize and take the minimum, mirroring
   `parser._parse_timestamp`'s `Z`→`+00:00` substitution technique
   (`parser.py:216-219`) — **but operating on the raw string from the entry
   dict, not on a `Message` object**. The parser is cited here for the technique
   only; `save_variance_record` does not call `parser._parse_timestamp`
   directly.
3. Format the result as an ISO-8601 UTC string and store it in `timestamp`.
4. If `ts_candidates` is empty (no entry carries a top-level timestamp), set
   `timestamp` to `null` — the aggregator's mtime fallback (§2 below) handles
   this at read time.

Thread the computed `timestamp` into the record in one of two ways:
- **Preferred:** add a `timestamp: str | None = None` parameter to
  `combine_variance` and pass the computed value. The record dict returned by
  `combine_variance` then includes `"timestamp": timestamp`.
- **Alternative:** set `record["timestamp"] = timestamp` on the dict returned
  by `combine_variance` in `save_variance_record`, before writing.

Either is acceptable; the preferred form keeps the schema expressed once inside
`combine_variance`.

**Signature change notice:** `combine_variance` (`variance_save.py:129-161`) is
the most-tested pure function in the producer — `TestCombineVariance` in
`tests/unit/test_variance_save.py` constructs it directly. If the preferred form
is chosen, those tests must be updated to pass `timestamp` (or assert the
default `None` path). Call this out in the Phase 0 PR description.

### Why not mtime as primary

File mtime is fragile under exactly the operations these records will undergo:
the records live under the plugin data dir, which may be copied, synced, or
migrated (the `_migrate_legacy_if_needed` path does a `shutil.move` that resets
mtimes on some platforms). A drift report keyed on mtime would silently
misattribute records to the wrong window after any such move. Rejected as the
primary mechanism — but see the fallback below.

### Why not cross-referencing the transcript at aggregation time

Option (c) (re-resolve each `session_id` to its transcript and read the start
time at report time) makes the aggregator depend on transcripts still existing
and still being resolvable. Transcripts are Claude Code's data, not ours; they
rotate and get cleaned up. Rejected.

### Fallback for records lacking `timestamp`

When a record has no `timestamp` field (records written before Phase 0 lands),
the aggregator falls back to the `variance/<id>.json` **file mtime** for that
record only, and counts it in a `records_without_timestamp` field in the JSON
output so the caller knows the window filter was approximate for those records.

**Temporal-distortion caveat:** the mtime fallback is unreliable for records
that have been through the legacy migration (`_migrate_legacy_if_needed`). That
migration uses `shutil.move`, which resets mtime on some platforms. For any user
who has already run the migration, every pre-`timestamp` record will have an
mtime near the migration date, not the session date — clustering all historical
records onto a single day in the trend chart. `records_without_timestamp`
surfaces the **count** of fallback records, but not their temporal distortion.
State this plainly in the text output when `records_without_timestamp > 0`:
"N records dated by file mtime — temporal position may be unreliable for
pre-migration records." The field self-heals as new records accrue after Phase 0
lands; only records written before Phase 0 are affected.

No backfill migration script is written (gold-plating — see §8).

## 3. Scope

### In scope

1. New deterministic subcommand `drift-report` in
   `src/claude_prospector/cli/drift_report.py`, registered in `__main__.py`.
2. A `load_variance_records(base_dir)` loader (no existing one) that globs
   `<base_dir>/variance/*.json` and returns parsed records, mirroring the glob
   discipline of `parser.parse_sessions` (`parser.py:556-609`).
3. `--window` / `--from` / `--to` flags reusing the existing
   `dashboard._parse_window` and `dashboard._parse_date` helpers
   (`dashboard.py:19-40` and `dashboard.py:43-61`) — do **not** reinvent date
   parsing. **`_parse_window` returns hours as a `float`; `_parse_date` returns
   a tz-aware `datetime`.** The `run()` function must convert the float to
   datetime bounds before passing them to `aggregate_drift` — see §6.
4. JSON output (primary, machine-readable contract) and a `--format text`
   human-readable trend summary.
5. One-field `timestamp` addition to the producer (§2 — ships as Phase 0, a
   separate small PR against `main` before this branch).
6. `session-analysis` skill extension: a new optional step that calls
   `drift-report` and renders the trend view in-session.
7. README updates: new `### drift-report` subcommand slot, skill-table row, and
   `session-analysis skill` section note; plus the `variance/<id>.json` schema
   gains the `timestamp` field (issue #63 AC: "README update including
   `variance/<id>.json` schema").

### Out of scope (explicitly — issue #63 + YAGNI)

- Real-time / live drift detection (issue #63: out of scope).
- Automated remediation (issue #63: out of scope).
- Cross-session / multi-task correlation (issue #63: out of scope).
- A dashboard / HTML surface for drift — see §8, flagged as gold-plating.
- A backfill migration script for legacy records — the field self-heals (§2).
- Config knobs beyond `--window` / `--from` / `--to` — see §8.

## 4. Output shape

### 4.1 JSON (default, `--format json`)

```json
{
  "window": { "from": "2026-05-26T00:00:00+00:00", "to": "2026-06-02T00:00:00+00:00" },
  "total_records": 14,
  "skipped_records": 0,
  "records_without_timestamp": 1,
  "drift": {
    "drifted": 5,
    "clean": 9,
    "drift_rate": 0.357
  },
  "severity_distribution": { "0": 7, "1": 3, "2": 2, "3": 1, "null": 1 },
  "trend": [
    { "date": "2026-05-26", "total": 2, "drifted": 1, "drift_rate": 0.5 },
    { "date": "2026-05-27", "total": 0, "drifted": 0, "drift_rate": 0.0 }
  ]
}
```

Field definitions:

- `window.from` / `window.to` — the resolved UTC bounds actually applied.
- `total_records` — records whose anchor time fell within the window and were
  successfully parsed. Does not include `skipped_records`.
- `skipped_records` — records that failed `json.loads` during loading. These
  are silently skipped (robustness over strictness) and do not appear in any
  other count. The command exits OK even when `skipped_records > 0`.
- `records_without_timestamp` — of the `total_records`, how many were dated by
  mtime fallback (§2). Surfaces window imprecision; `0` in the steady state.
  When non-zero, the text format adds a warning about temporal distortion.
- `drift.drifted` — records classified as drifted (severity-primary rule, §5).
  `clean = total_records - drifted`.
- `drift.drift_rate` — `drifted / total_records`, rounded to **3 decimal
  places**; `0.0` when `total_records` is 0 (no division-by-zero). The
  `claude-configs#535` threshold consumer should expect exactly 3 decimal
  places.
- `severity_distribution` — histogram across all `total_records` (both clean
  and drifted). Keys `"0"`–`"3"` are the documented scale
  (`skills/session-analysis/SKILL.md:80-82`); `"null"` is its own bucket (see
  §5). All five keys are always present, value `0` when empty.
  **Invariant:** `sum(severity_distribution.values()) == total_records`. The
  distribution counts every counted record (clean + drifted), while
  `drift.drifted` counts only drifted records — two different denominators,
  reconciled by `clean = total_records - drifted`.
- `trend` — one entry per **calendar day** (UTC) in `[from, to)`, including
  days with zero records (`total: 0`), so a consumer can plot a continuous
  series. Capped at 366 days maximum (see §6 for the cap and the inverted-range
  error).

### 4.2 Text (`--format text`) — what the skill renders

```
Drift report — 2026-05-26 to 2026-06-02 (7d)
  Sessions analyzed:  14   (1 dated by file mtime — temporal position may be unreliable for pre-migration records)
  Drifted:            5 / 14  (36%)
  Severity:           0:7  1:3  2:2  3:1  null:1

  Trend (drift rate by day):
    05-26  ##########          50%  (1/2)
    05-27  (no sessions)
    05-28  ###                 14%  (1/7)
    ...
```

The text renderer is deliberately plain (ASCII bars from the per-day
`drift_rate`). No color, no Unicode sparklines — keep it lean and
copy-pasteable. The skill (§7) wraps this with a one-line interpretive verdict;
the CLI itself emits no interpretation.

## 5. Severity bucketing and drift definition

**`severity` is `int | null`** (`variance_save.py:46`, skill scale 0–3 at
`session-analysis/SKILL.md:80-82`). Bucketing rule:

- A record with `severity` 0, 1, 2, or 3 → counted in that integer bucket.
- A record with `severity: null` (or the key absent) → counted in the `"null"`
  bucket. `null` is **not** coerced to 0 — "no number assigned" is semantically
  distinct from "0, on task" (the skill says null = "can't justify a number",
  `SKILL.md:82`). Conflating them would distort the distribution.
- A `severity` value outside 0–3 (malformed record) → counted in `"null"` and
  the record is otherwise processed normally (robustness over strictness; we do
  not reject the whole record for one bad field).

**Drift definition — severity-primary, prose fallback:**

1. **Severity is present (0, 1, 2, or 3):** the severity value is the
   authoritative drift signal. A record is **drifted** iff `severity` ∈ {1,2,3};
   **clean** iff `severity == 0`. The `variance` prose is not consulted.
2. **Severity is null or absent:** fall back to the `is_drifted(variance)`
   prose check. A record counts as drifted when its `variance` string, after
   `.strip()`, is non-empty and is not one of the no-drift sentinels.

**`is_drifted` prose sentinel set (null-severity fallback only):**

SKILL.md (`SKILL.md:74`) mandates exactly one clean-session phrasing: the
literal `"no variance"`. Match case-insensitively against `{"no variance"}` as
the primary sentinel. The empty string `""` (after strip) is also treated as
clean. Everything else with prose content is "drifted".

> Note: the sentinel set is intentionally small and verified against
> `SKILL.md:74`. The 1b skill is instructed to write `"no variance"` for clean
> sessions — only that exact phrasing is documented. Do not expand the set
> without verifying against real 1b output and updating the skill instructions
> in lockstep. `{"none", "n/a"}` are **not** in the set — they are not
> mandated by the skill and adding speculative sentinels risks silently dropping
> real (terse) drift findings.

> The `is_drifted` fallback only matters for records where `severity` is
> null. As severity adoption increases (every new record from the 1b skill
> will carry it per `SKILL.md:80-82`), the prose fallback becomes a backstop
> for legacy records only.

## 6. Module structure (mirror existing CLI pattern)

Per the map, every subcommand module exports `build_parser(parent)` +
`run(args) -> int` and is dispatched in `__main__.py` by `args.subcommand`
(`__main__.py:34-37` — subparsers setup; `__main__.py:39-44` — build_parser
calls; `__main__.py:52-68` — dispatch chain). Mirror `variance_save.py`
(`build_parser` at `variance_save.py:307-371`, `run` at `variance_save.py:373-426`)
and `session_audit.py`.

```
src/claude_prospector/cli/drift_report.py

  EXIT_OK = 0
  EXIT_IO_FAILURE = 1                      # mirror per-module exit constants

  # Pure logic (no I/O) — unit-testable directly:
  def load_variance_records(base_dir: Path) -> list[dict]
  def record_anchor_time(record: dict, file_mtime: float) -> datetime   # §2 fallback
  def is_drifted(variance: str) -> bool                                 # §5 prose fallback (null-severity only)
  def severity_bucket(severity) -> str                                  # §5 → "0".."3"|"null"
  def aggregate_drift(records, from_dt: datetime, to_dt: datetime) -> dict   # → §4.1 shape
  def render_text(report: dict) -> str                                  # → §4.2 shape

  # CLI plumbing:
  def build_parser(parent) -> argparse.ArgumentParser
  def run(args) -> int
```

`run` resolves `base_dir()` from `paths.py` (default) unless `--base-dir` is
given (test override, mirrors `variance-save --out`/`--data-dir` decoupling),
calls `load_variance_records`, resolves the window **to UTC datetime bounds**,
calls `aggregate_drift`, and prints JSON or `render_text` output.

### Window resolution in `run()` — required conversion step

`dashboard._parse_window` returns **hours as a float** (`dashboard.py:19-40`).
`aggregate_drift` takes `from_dt` and `to_dt` as tz-aware `datetime` objects.
`run()` must perform the conversion explicitly:

```python
from datetime import datetime, timedelta, timezone

# --window path (default: 7d = 168.0 hours)
now = datetime.now(timezone.utc)
from_dt = now - timedelta(hours=window_hours)
to_dt = now

# --from / --to path (already datetime from _parse_date)
from_dt = args.from_date
to_dt = args.to_date if args.to_date is not None else datetime.now(timezone.utc)
```

`_parse_date` returns a tz-aware datetime (`dashboard.py:43-61`), so the
`--from/--to` path requires no further conversion.

### Range validation

Before passing bounds to `aggregate_drift`, `run()` must validate:
- If `from_dt >= to_dt`: exit with an argparse-style error ("invalid range:
  `--from` must precede `--to`"). This prevents inverted-range edge cases from
  producing empty or nonsensical output silently.
- If `(to_dt - from_dt).days > 366`: exit with an error ("window exceeds 366
  days — use a narrower range"). This caps the `trend` array and prevents
  multi-megabyte output on wide absolute-date queries.

Document both limits in the `--window` / `--from` / `--to` help strings and in
the README flags table.

### Flags

| Flag | Purpose | Default |
|---|---|---|
| `--window` | Relative window (`7d`, `48h`) via `dashboard._parse_window` (returns hours) | `7d` |
| `--from` / `--to` | Absolute `YYYY-MM-DD` bounds via `dashboard._parse_date` (returns UTC datetime) | none |
| `--format` | `json` (default) or `text` | `json` |
| `--base-dir` | Override variance-records root (tests) | `paths.base_dir()` |

`--window` and `--from/--to` are mutually exclusive (argparse mutually
exclusive group); if `--from` without `--to`, `--to` defaults to now (UTC).
Reuse the dashboard parsers verbatim — they already raise
`argparse.ArgumentTypeError` on bad input (`dashboard.py:33-35` and
`dashboard.py:59-61`).

### Exit codes

- `EXIT_OK = 0` — success; JSON or text written to stdout.
- `EXIT_IO_FAILURE = 1` — unreadable variance directory or OS-level error. A
  record that fails `json.loads` is **not** an IO failure: it is skipped
  silently and counted in `skipped_records` (§4.1); the command still exits 0.
  Only a failure to open/read a file at the OS level triggers exit 1.

## 7. session-analysis skill extension

The skill is the in-session front-end (`session-analysis/SKILL.md`). Add a new
**optional** step after the existing per-session flow:

> ## Step 6 (optional) — Aggregate trend across sessions
>
> When the user wants the bigger picture ("am I drifting more lately?", "show me
> drift trends"), run the deterministic aggregator and render its text output:
>
> ```bash
> python -m claude_prospector drift-report --window 7d --format text
> ```
>
> This reads all persisted `variance/<id>.json` records — no LLM cost, no
> transcript reads. Surface the text summary, then add **one** interpretive
> line (is the trend rising, is severity clustering high?). The CLI emits
> numbers; you add the one-sentence read. Do not re-derive the numbers.

Keep it to one step. The skill must not recompute or re-interpret the per-record
fields — the division of labor (deterministic CLI vs. one-line LLM verdict) is
the whole point of the 1a/1b/aggregate split (`SKILL.md:26-32`).

Also update the skill `description` trigger phrases to include the aggregate
intent (e.g. "show me drift trends", "am I drifting more lately") so the
dispatcher routes those to this skill.

## 8. Gold-plating flags (YAGNI — per user's stated over-engineering tendency)

Called out explicitly so they are decisions, not omissions:

- **HTML/dashboard surface for drift** — tempting to mirror the usage dashboard,
  but #63 needs a machine-readable signal for `claude-configs#535`, not a
  visual. A text trend + JSON covers both the human and the machine consumer.
  **Recommend: do not build.** Revisit only if a concrete consumer asks.
- **Backfill migration script** for pre-`timestamp` records — the field
  self-heals as new records accrue, and the mtime fallback (§2) covers the
  transition. A migration script is write-once throwaway code for a problem that
  evaporates. **Recommend: do not build.**
- **Configurable drift/sentinel matcher** — the `is_drifted` prose fallback (§5)
  uses a small, verified sentinel set. A regex/config knob is speculative.
  **Recommend: hard-code, document, test.**
- **Per-project / per-agent drift breakdown** — that is cross-session
  correlation, explicitly out of scope (#63). The record schema does not even
  carry a project field. **Recommend: do not build.**
- **Trend smoothing / moving averages / anomaly flags** — raw per-day rate is
  enough for a human eyeball and a `soft_deny` threshold. **Recommend: do not
  build.**

If the user wants any of these, they should be separate issues scoped on their
own merits — not folded into #63's remaining ACs.

## 9. Testing

Mirror `tests/unit/test_variance_save.py` (per map): temp-dir fixtures
(`tmp_path / "variance"`), a record-builder helper, subprocess `_run_cli()` for
end-to-end and direct function calls for the pure logic. New file
`tests/unit/test_drift_report.py`. Required cases:

- **Pure logic:**
  - `is_drifted` (prose fallback — null-severity records only): prose → True;
    `""`, `"no variance"` (and case variants: `"No Variance"`, `"NO VARIANCE"`) →
    False; whitespace-only → False.
  - Severity-primary path: `severity=0` → clean regardless of `variance` prose;
    `severity=1` → drifted regardless of `variance` prose; `severity=2` →
    drifted; `severity=3` → drifted; `severity=None` + non-empty variance →
    falls back to `is_drifted`.
  - `severity_bucket`: 0/1/2/3 → own bucket; `None` → `"null"`; missing key →
    `"null"`; out-of-range (e.g. `7`, `-1`) → `"null"`.
  - `aggregate_drift`: empty record set → `drift_rate 0.0`, all severity buckets
    present and 0, empty `trend` spanning the window; mixed set → correct counts,
    rate, distribution; window filtering excludes out-of-range records.
  - `aggregate_drift` sum invariant: `sum(severity_distribution.values()) ==
    total_records` for every output (assert in at least one mixed-record test).
  - `record_anchor_time`: record with `timestamp` uses it; record without uses
    the passed mtime and the record is counted in `records_without_timestamp`.
  - `trend` includes zero-record days within the window (continuity).
  - `skipped_records`: a directory containing one valid record and one
    unparseable JSON file → `total_records=1`, `skipped_records=1`, exit 0.
- **End-to-end (`_run_cli`):**
  - JSON output shape matches §4.1 against a fixture directory of records.
  - `--format text` renders §4.2 without crashing; spot-check a line.
  - `--window 7d` (default) produces correct `window.from` / `window.to` in JSON
    output — this exercises the float-hours → datetime-bounds conversion in
    `run()`, which is the most likely unit to be wrong (do not test
    `aggregate_drift` in isolation with pre-built bounds only).
  - `--window` and `--from/--to` mutually exclusive → argparse error exit.
  - Bad `--window` / `--from` format → `argparse.ArgumentTypeError` exit.
  - Inverted range (`--from` after `--to`) → error exit.
  - Window exceeding 366 days → error exit.
  - Empty `variance/` dir (or missing) → valid zero report, exit 0.
- **Producer tests (Phase 0 — `tests/unit/test_variance_save.py`):** a record
  written by `variance-save` now carries `timestamp`; assert it equals the
  earliest entry timestamp from the fixture transcript. If `combine_variance`
  receives a new `timestamp` parameter, update `TestCombineVariance` to cover
  both the `timestamp=None` (legacy) and `timestamp=<str>` (field present)
  paths.

All invoked via `uv run pytest` (project CLAUDE.md — bare `pytest` falls through
to system Python 3.14).

## 10. Phasing

### Phase 0 — `timestamp` producer field (separate small PR against `main`)

- **Entry:** PR #213 merged to `main` (commit `80cce27` — already done).
- **Branch:** cut a fresh branch off `main` (not off `63-drift-aggregation`)
  for this small producer change.
- **Deliverables:** `timestamp` derivation in `save_variance_record`
  (`variance_save.py:239-258`), threaded into `combine_variance` (or set on the
  returned dict); updated `tests/unit/test_variance_save.py` (`TestCombineVariance`
  and a new producer integration test).
- **Exit:** `uv run pytest tests/unit/test_variance_save.py` green; record
  written by `variance-save` carries `timestamp` equal to earliest entry time.
  Merge to `main` before starting Phase 1.

### Phase 1 — CLI engine (the deterministic core)

- **Entry:** Phase 0 merged to `main`; `63-drift-aggregation` rebased or reset
  onto the Phase 0 commit. Pre-field records (written before Phase 0) are handled
  by the mtime fallback; no gate needed on their absence.
- **Deliverables:** `drift_report.py` (loader + pure logic + plumbing),
  `__main__.py` registration, full `test_drift_report.py`.
- **Exit:** `uv run pytest tests/unit/test_drift_report.py` green; `uv run ruff
  check src/ tests/` clean; `python -m claude_prospector drift-report
  --format json` runs against a real `variance/` dir.

### Phase 2 — Skill front-end

- **Entry:** Phase 1 merged or on the same branch, CLI callable.
- **Deliverables:** `session-analysis/SKILL.md` Step 6 + trigger-phrase update.
- **Exit:** skill text references the exact CLI invocation; no recomputation of
  CLI-owned fields; Skill Smoke CI passes.

### Phase 3 — Docs

- **Deliverables:** README `### drift-report` subcommand slot (usage, flags
  table, JSON schema, example output, exit-codes table — mirror the
  `session-audit` slot at `README.md:269`), skill-table row (`README.md:9`),
  `session-analysis skill` section note, and the `variance/<id>.json` schema
  updated with the `timestamp` field (#63 AC).
- **Exit:** README accurate; PR body uses `Closes #63` (verify #63 has no other
  open ACs before claiming closure).

## 11. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phase 0 `combine_variance` signature change breaks `TestCombineVariance` | High (certain if preferred form chosen) | Low | Expected — call it out in the Phase 0 PR; update the tests as part of the same commit. |
| `timestamp` field absent on pre-Phase-0 records | Certain (by design) | Low | mtime fallback (§2) + `records_without_timestamp` count; self-heals as new records accrue. |
| mtime fallback misattributes migrated records (all collapse to migration date) | Medium (affects users who have run the legacy migration) | Medium | `records_without_timestamp` surfaces the count; text format warns about temporal distortion. Trend data for pre-Phase-0 records is unreliable for users post-migration; this is disclosed, not hidden. |
| `_parse_window` float → datetime conversion missing or wrong in `run()` | Medium | High | §9 requires a `--window 7d` end-to-end test through `run()` — this is the acceptance gate for the conversion. |
| 1b "no variance" phrasing changes without updating the sentinel set | Low | Medium | Sentinel set verified against `SKILL.md:74`; §5 note flags the lockstep requirement; `is_drifted` is tested. Since severity is now the primary signal, the prose fallback only matters for null-severity records — its blast radius is smaller than the original design. |
| Unbounded `trend` array on wide absolute-date window | Low | Medium | Hard cap at 366 days + inverted-range validation in `run()` (§6); both exercised in §9 tests. |
| Wheel packaging (new module) | Low | Low | Pure-Python module under `src/claude_prospector/cli/` — no template/package-data change, so no wheel-smoke risk (project CLAUDE.md § CI gates). Confirm `unzip -l` still ships the module if any packaging doubt. |

## 12. Definition of done

- `drift-report` subcommand reads `variance/*.json`, applies the window, emits
  the §4.1 JSON and §4.2 text shapes (#63 ACs: drift-aggregation CLI + trend
  report).
- Severity-primary drift rule and `is_drifted` prose fallback implemented per §5
  and tested, including the sum invariant for `severity_distribution`.
- `session-analysis` skill renders the trend (#63: 1b front-end parity).
- README documents the subcommand and the updated `variance/<id>.json` schema
  (#63 AC).
- Opt-in preserved — aggregation only runs on demand over collected records
  (#63 AC; locked decision 3).
- `uv run pytest` + `uv run ruff check` green; PR body `Closes #63`.
