# claude-prospector

Claude Code efficiency and hygiene toolkit. Surfaces token spend across the three billing windows with per-model / per-agent / per-skill attribution, and audits your effective Claude Code configuration for agent and skill overlap.

## Why

`claude-prospector` bundles a set of skills that target distinct angles of "is my Claude Code setup healthy?":

| Skill | Angle |
|---|---|
| `usage-analysis` | where your tokens are going |
| `usage-dashboard` | regenerate the cost dashboard surface |
| `claude-audit` | where your config has agent / skill overlap or bloat |
| `session-analysis` | whether a session stayed on task (opt-in LLM judgment) |

Claude Code's built-in `/usage` shows current-session token totals and — for Max/Pro subscribers — plan-usage bars on the same screen. It doesn't surface multi-day history, per-agent attribution with sub-agent nesting, per-skill invocation counts, or per-project breakdowns, and there's no way to ask "where are my Sonnet-7d tokens going this week?" from inside the session. There's also no built-in way to detect when two installed plugins ship overlapping `code-reviewer` agents or near-duplicate skills.

`claude-prospector` reads Claude Code's local JSONL session files to break tokens down by model, agent (with sub-agent nesting), skill, and project across all three billing windows (5h rolling, 7d rolling, Sonnet-only 7d), and inventories your custom + plugin-provided agents and skills to produce a structured overlap / conflict report with keep / modify / drop recommendations.

## Install

### 1. Add the marketplace and install the plugin

```bash
claude plugin marketplace add glitchwerks/plugins
claude plugin install claude-prospector@glitchwerks
```

### 2. First-run setup

After installing (or after a plugin update), open a new Claude Code session. You will see a banner:

> claude-prospector requires setup. Run /setup-prospector to materialise the Python venv. After setup completes, open a new session to activate the dashboard, skill-tracking, and usage-analysis features.

Run `/setup-prospector` once. The skill will:

1. Discover a Python 3.10+ interpreter on your system.
2. Create a plugin-owned venv at `${CLAUDE_PLUGIN_DATA}/venv/`.
3. Install `claude-prospector` from PyPI into that venv.
4. Verify the install and record a setup-state flag.

After setup completes, open a new session — the banner will be gone and all features will work normally.

You will need to re-run `/setup-prospector` only when:

- The plugin updates to a new version (banner: "venv is for vX but plugin is vY").
- The venv is corrupted or deleted (banner: "venv at `<path>` is unreachable or corrupt").
- You move to a new machine (setup is per-machine; the flag is not portable).

## What you can do

### `usage-analysis` skill

Conversational analysis with recommendations. Triggered by natural-language phrases such as:

- "am I close to my Sonnet limit?"
- "where are my tokens going?"
- "which agent uses the most tokens?"
- "give me a usage analysis"

The skill reads your session data and responds inline — no browser required.

### `usage-dashboard` skill

Bare dashboard regeneration. Triggered by phrases like "regenerate the dashboard" or "rebuild my usage dashboard". Writes the HTML file and reports the path, without interpreting the data.

The generated HTML dashboard includes:

- **Budget gauges** — estimated usage against each billing bucket (5h / 7d / Sonnet-only 7d)
- **Model breakdown** — donut chart and daily stacked bar chart (Opus / Sonnet / Haiku)
- **Agent breakdown** — token usage per agent with model attribution and nested sub-agent tracing
- **Skill usage** — invocation counts per skill
- **Project breakdown** — tokens per project
- **Session drill-down** — click a day to see individual sessions with agents, tokens, and model split

### `claude-audit` skill

Audits your project's effective Claude Code configuration — custom and plugin-provided agents and skills together — and produces a structured overlap / conflict report with keep / modify / drop recommendations scoped to the project's stated objectives. Triggered by `/claude-prospector:claude-audit` or natural-language phrases such as:

- "audit my claude config"
- "find overlap in my agents"
- "check for skill conflicts"
- "are any of my agents duplicates"
- "what's redundant in my setup"

The skill is read-only — it does not modify any files. All recommendations are presented for your review.

### `session-analysis` skill

The interpretive (LLM) complement to the deterministic `session-audit` CLI. Where `session-audit` extracts ask-vs-done for free, `session-analysis` adds the judgment layer: did the agent stay on the original ask, and what did it acknowledge skipping?

The skill loads `session-audit`'s extract (the 1a fields), then has the agent produce two judgment fields — `Variance` and `What was NOT done` — and persists a combined record via the `variance-save` subcommand.

**Key constraints:**

- **Opt-in, not automatic.** Costs ~1-3k tokens of the current session; run it selectively on sessions you suspect drifted, not on every session.
- **Sonnet or stronger recommended.** Judgment quality depends on the model.

Trigger phrases: `/session-analysis`, "did this session stay on task", "analyze session drift", "did the agent do what I asked", "what did this session skip".

Cross-references:
- `session-audit` — free deterministic ask/actions extract (run this first)
- `usage-analysis` — token-spend insights
- `claude-audit` — agent/skill config overlap

The full skill definition is at `skills/session-analysis/SKILL.md`.

### `setup-prospector` skill

First-run and post-update setup. Triggered by `/setup-prospector` or phrases like "set up claude-prospector", "fix prospector", or "prospector isn't working". See [Install](#install) for the full walkthrough.

### SessionStart hook (`check-prospector-setup.py`)

Fires once at the beginning of every session. Checks setup state and emits a banner when setup is missing, stale, or broken. Silent when everything is valid. This hook never blocks the session.

### `skill-tracker` hook (`skill-tracker.py`, PreToolUse)

Logs `Skill` and `Agent` tool-use events to the state directory for the `by_skill` and skill-passed-vs-invoked analyses. Gated on VALID setup state — if you skip `/setup-prospector`, skill-tracking is silently inactive until setup is complete.

### `dashboard-regen` hook (Stop, opt-in)

Auto-regenerates the dashboard after every session when `autoregen` is enabled. Off by default; toggle via the plugin manager (see [Configuration](#configuration)).

## Configuration

The `dashboard-regen` Stop hook is opt-in. Toggle it through the Claude Code plugin manager — no manual file edits required:

```
/plugin reconfigure claude-prospector
```

You will be prompted to enable or disable `autoregen`. You can also set it at install time when the plugin manager shows the initial configuration prompt.

To inspect the current plugin configuration, use the read-only CLI:

```bash
python -m claude_prospector config --show
```

When a config file exists, this prints its contents as pretty-printed JSON to stdout.
When no config file exists, it prints `(no config file yet)` and a redirect note to stderr, and `{}` to stdout. Exit code is 0 in both cases.

The authoritative `autoregen` value is whatever is set in the plugin manager — not the legacy `config.json`.

### Hiding noise projects from the dashboard

Claude Code creates session directories for every working directory it opens,
including Electron app internals, Warp terminal worktrees, and other
non-project paths. You can hide these from the dashboard's project view by
adding a `project_exclude_patterns` list to your `config.json`:

```json
{
  "project_exclude_patterns": [
    "AppData\\Local\\Programs",
    "warp\\Warp\\data\\worktrees",
    "AppData\\Roaming\\Open-Design"
  ]
}
```

Each entry is a **case-sensitive substring** matched against the full project
path (the `cwd` field from the session, or the decoded directory slug when no
`cwd` is available). A session is hidden when its project path contains any
listed pattern. The default is an empty list — no projects are hidden.

The config file is located at `base_dir() / "config.json"` (override with
`CLAUDE_PROSPECTOR_CONFIG`). Edit it with any text editor; it is read on every
`dashboard` invocation.

### Project labels in the dashboard

The dashboard now shows the **leaf directory name** (e.g. `claude-prospector`)
as the project label instead of the full encoded slug. Hover over any project
name to see the full path in a tooltip.

The leaf name is derived from the `cwd` field recorded in the session when
available (most accurate), falling back to the last segment of the encoded
directory name.

## Environment variables

| Variable | Controls | Notes |
|---|---|---|
| `CLAUDE_PLUGIN_DATA` | Venv placement and default state/dashboard storage | Set by the Claude Code plugin host; do not override in normal use |
| `CLAUDE_PROSPECTOR_BASE_DIR` | State and dashboard storage for hooks and CLI | Overrides `CLAUDE_PLUGIN_DATA` for hooks/CLI only; does not affect the venv location |
| `CLAUDE_PROSPECTOR_CONFIG` | `config.json` path | Overrides the default `<base_dir>/config.json` |
| `CLAUDE_PROSPECTOR_DASHBOARD` | `dashboard.html` path | Overrides the default `<base_dir>/dashboard.html`; the `dashboard` subcommand's `--output` flag overrides a single run without setting this |
| `CLAUDE_PROSPECTOR_HOOK_LOG` | `hook.log` path | Overrides the default `<base_dir>/hook.log` |
| `CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR` | `skill-tracking/` directory path | Overrides the default `<base_dir>/skill-tracking/` |
| `CLAUDE_PROSPECTOR_PIP_SPEC` | The pip spec used by `/setup-prospector` | Overrides the default `claude-prospector==<version>` — used in CI and dev to install from TestPyPI or a local checkout |

## Troubleshooting

The SessionStart hook emits one of four banner states. Use the banner text to decide what to do:

**MISSING** — No setup-state flag found, or the previous venv failed the per-session import probe.

> claude-prospector requires setup. Run /setup-prospector to materialise the Python venv. After setup completes, open a new session to activate the dashboard, skill-tracking, and usage-analysis features.

Action: run `/setup-prospector`, then open a new session.

**STALE** — The flag records a different plugin version than the one currently installed.

> claude-prospector venv is for v`<flag_version>` but plugin is v`<current_version>`. Run /setup-prospector to refresh the venv.

Action: run `/setup-prospector` to rebuild the venv for the new version.

**BROKEN** — The flag exists and the version matches, but the venv path is unreachable or corrupt.

> claude-prospector venv at `<venv_path>` is unreachable or corrupt. Run /setup-prospector to recreate it.

Action: run `/setup-prospector` to recreate the venv.

**VALID (probe failed)** — The flag looks valid but the per-session `import claude_prospector` probe failed. The hook downgrades state to MISSING and emits the MISSING banner.

Action: same as MISSING — run `/setup-prospector`, then open a new session.

**Silent session** — No banner emitted. Setup is valid and the import probe passed. All features are active.

## Subcommands

All functionality is accessed through named subcommands. Bare `claude-prospector` (no subcommand) prints help and exits 0.

### `dashboard` — interactive HTML dashboard

```bash
# Default: last 7 days, opens in browser
python -m claude_prospector dashboard

# Rolling window matching Claude billing buckets
python -m claude_prospector dashboard --window 5h
python -m claude_prospector dashboard --window 7d

# Custom date range
python -m claude_prospector dashboard --from 2026-04-01 --to 2026-04-09

# Output to file instead of opening browser
python -m claude_prospector dashboard --output report.html --no-open

# Custom Claude data directory
python -m claude_prospector dashboard --data-dir "D:\other\.claude"

# Set budget limits for gauge percentages
python -m claude_prospector dashboard --limit-5h 600000 --limit-7d 4000000 --limit-sonnet-7d 2000000

# Emit JSON for scripting or CI
python -m claude_prospector dashboard --format json
```

### `session-summary` — deterministic session recap

Reads a single Claude Code transcript JSONL file and emits a structured JSON summary suitable for consumption by the `/whats-next` skill or any other tool that needs to know what a session did.

```bash
python -m claude_prospector session-summary --path ~/.claude/projects/<hash>/<session>.jsonl
```

**Flags:**

| Flag | Default | Description |
|---|---|---|
| `--path PATH` | *(required)* | Path to the transcript JSONL file |
| `--format {json,text}` | `json` | Output format. `json` is the machine-readable contract; `text` is a human-readable debug view |
| `--max-actions N` | `50` | Cap on emitted actions. `0` disables the cap |

**Sample output (`--format json`):**

```json
{
  "project": "claude-prospector",
  "intent": "Implement the session-summary subcommand for the /whats-next skill",
  "actions": [
    "Edited claude_prospector/cli/session_summary.py",
    "Created tests/test_session_summary.py",
    "Ran pytest tests/test_session_summary.py -x",
    "Dispatched code-reviewer sub-agent"
  ],
  "stoppedNaturally": true
}
```

**Exit codes:**

| Code | Meaning | stderr |
|---|---|---|
| `0` | Success — JSON written to stdout | *(silent)* |
| `1` | IO failure reading `--path` (file missing, permission denied, etc.) | `session-summary: cannot read transcript at '<path>': <OSError class>: <message>` |
| `2` | File readable but contains no external user turns | `session-summary: transcript '<path>' contains no user turns` |
| `3` | File has content but none of it parses as JSONL | `session-summary: transcript '<path>' is not valid JSONL` |

On any non-zero exit, stdout is empty and stderr contains exactly one line.

### `session-audit` — ask-vs-action extraction at zero LLM cost

```bash
# By path
python -m claude_prospector session-audit --path <transcript.jsonl>

# By session-id (resolves transcript under ~/.claude/projects/)
python -m claude_prospector session-audit --session-id <id>
```

Reads a single Claude Code session transcript (`.jsonl`) and emits
structured data capturing what was asked and what file edits were made,
with **no API calls**.

#### Flags

| Flag | Default | Description |
|---|---|---|
| `--path <file>` | *(mutually exclusive with `--session-id`)* | Path to the transcript JSONL file |
| `--session-id <id>` | *(mutually exclusive with `--path`)* | Session id; the transcript is resolved under `~/.claude/projects/` (override root with `--data-dir`) |
| `--format json\|text` | `json` | Output format |
| `--batch` | off | *(not yet implemented)* Walk `~/.claude/projects/**/*.jsonl` and emit per-session array |

#### JSON schema (`--format json`)

```json
{
    "original_ask": "<string or null>",
    "prior_asks":   ["<string>", "..."],
    "actions":      [
        {"tool": "<Edit|Write|NotebookEdit>", "file_path": "<string>"},
        "..."
    ]
}
```

| Field | Type | Description |
|---|---|---|
| `original_ask` | `string \| null` | Verbatim text of the **first** non-system, non-tool-result external user message. `null` when absent. |
| `prior_asks` | `string[]` | Verbatim text of each subsequent distinct user ask, in transcript order. Empty array for single-ask sessions. |
| `actions` | `object[]` | Chronologically ordered `Edit`/`Write`/`NotebookEdit` tool_use events. Bash invocations excluded. |

#### Example output

```json
{
  "original_ask": "Add a --dry-run flag to the CLI.",
  "prior_asks": [
    "Now also write tests for it.",
    "close the pr"
  ],
  "actions": [
    {"tool": "Edit", "file_path": "src/claude_prospector/__main__.py"},
    {"tool": "Write", "file_path": "tests/test_dry_run.py"}
  ]
}
```

#### Exit codes

| Code | Meaning | stderr |
|---|---|---|
| `0` | Success — output written to stdout | *(silent)* |
| `1` | IO failure reading `--path` (file missing, permission denied, etc.) | `session-audit: cannot read transcript at '<path>': <OSError class>: <message>` |
| `2` | File readable but contains no external user turns | `session-audit: transcript '<path>' contains no user turns` |
| `3` | File has content but none of it parses as JSONL | `session-audit: transcript '<path>' is not valid JSONL` |

On any non-zero exit, stdout is empty and stderr contains exactly one line.

---

### `variance-save` — persist combined audit + judgment

```bash
# Judgment supplied as a file
python -m claude_prospector variance-save --session-id <id> --judgment-file <f>

# Judgment supplied on stdin (--judgment-file omitted)
python -m claude_prospector variance-save --session-id <id> < judgment.json
```

Re-runs `session-audit` internally (1a), merges the result with the supplied judgment JSON, and writes a combined record. Transcript search and output location are independent — the transcript is resolved under `~/.claude/projects/` (override with `--data-dir`); output goes to `<plugin-data-dir>/variance/<session-id>.json` by default (override with `--out <path>`). Prints the written path on success.

#### Judgment input shape

```json
{"variance": "<str>", "not_done": "<str>", "severity": <int|null>}
```

`severity` is optional (0 = on task, 1 = minor drift, 2 = notable scope or skipped ask, 3 = session largely off task).

#### Combined output schema

```json
{
  "session_id": "<id>",
  "original_ask": "<str|null>",
  "prior_asks": ["<str>"],
  "actions": [{"tool": "<Edit|Write|NotebookEdit>", "file_path": "<str>"}],
  "variance": "<str>",
  "not_done": "<str>",
  "severity": "<int|null>",
  "timestamp": "<ISO-8601 str, UTC-assumed|null>",
  "prompts_redacted": <true|false>
}
```

`timestamp` is the earliest raw-transcript-entry timestamp, or `null` when none is found. It is assumed already UTC — a naive (offset-less) value is tagged as UTC, but a value carrying an explicit non-UTC offset (e.g. `+05:00`) is preserved as-is, not converted. `prompts_redacted` reflects whether `--redact-prompts` was passed: `true` means `original_ask` is `null` and `prior_asks` is `[]`; `false` (the default) means both fields hold the verbatim captured text. This artifact is the input to the `drift-report` subcommand below, which reads every record under `<base_dir>/variance/`.

| Flag | Default | Description |
|---|---|---|
| `--session-id <id>` | *(required)* | Session id; transcript resolved under `--data-dir` |
| `--judgment-file <f>` | stdin | Path to the judgment JSON file; omit to read from stdin |
| `--data-dir <dir>` | `~/.claude` | Root under which `projects/` is searched for the transcript |
| `--out <path>` | `<plugin-data-dir>/variance/<id>.json` | Override the output path |
| `--redact-prompts` | `False` | Write `null`/`[]` for `original_ask`/`prior_asks` instead of the verbatim text, and set `prompts_redacted: true` in the output record |

#### Exit codes

| Code | Meaning | stderr |
|---|---|---|
| `0` | Success — combined record written; path printed to stdout | *(silent)* |
| `1` | IO failure (transcript missing, judgment unreadable, output unwritable) | `variance-save: <reason>` |
| `2` | Transcript found but contains no user turns | `variance-save: transcript '<path>' contains no user turns` |
| `3` | Judgment input is not valid JSON or missing required fields | `variance-save: judgment: <reason>` |

---

### `drift-report` — aggregate drift across variance records

```bash
# Default: last 7 days, machine-readable JSON
python -m claude_prospector drift-report

# Relative window
python -m claude_prospector drift-report --window 48h

# Absolute date range
python -m claude_prospector drift-report --from 2026-07-01 --to 2026-07-08

# Human-readable text summary
python -m claude_prospector drift-report --format text

# Custom variance-records root
python -m claude_prospector drift-report --base-dir /path/to/base
```

Reads every `<base_dir>/variance/*.json` record written by `variance-save`, filters to a time window, and computes drift frequency, severity distribution, and a per-day trend. No LLM cost — purely deterministic aggregation over records already on disk.

This is the last acceptance criterion from the drift-aggregation epic (issue #63, closed); the aggregation logic itself shipped in PR #220.

#### Flags

| Flag | Default | Description |
|---|---|---|
| `--window WINDOW` | `7d` | Relative time window, e.g. `7d` or `48h`. Maximum effective range is 366 days. Mutually exclusive with `--from` |
| `--from YYYY-MM-DD` | *(none)* | Absolute start date (inclusive). Defaults `--to` to now if omitted. Mutually exclusive with `--window`. Range must not exceed 366 days |
| `--to YYYY-MM-DD` | now | Absolute end date (exclusive). Not part of the `--window`/`--from` mutually exclusive group — pairs with `--from`; ignored if `--window` is also given |
| `--format {json,text}` | `json` | `json` is the machine-readable contract; `text` renders an ASCII summary with a per-day trend bar chart |
| `--base-dir PATH` | plugin data base dir | Root whose `variance/` sub-directory is scanned. Resolved from `CLAUDE_PROSPECTOR_BASE_DIR` > `CLAUDE_PLUGIN_DATA` > `~/.claude/claude-prospector` when omitted. This is the **variance-records root**, independent of `session-audit`/`variance-save`'s `--data-dir` (transcript root) — if `variance-save --out` wrote records elsewhere, point `--base-dir` there too |

#### JSON schema (`--format json`)

The block below is a type-annotated illustration, not literal output: `int`/`float` fields are shown unquoted with a trailing comment giving their type, while `<...>` placeholders mark string fields whose actual value varies.

```jsonc
{
    "window": {
        "from": "<ISO-8601 UTC>",
        "to":   "<ISO-8601 UTC>"
    },
    "total_records":             0,    // int
    "skipped_records":           0,    // int
    "records_without_timestamp": 0,    // int
    "drift": {
        "drifted":    0,               // int
        "clean":      0,               // int
        "drift_rate": 0.0              // float, 3 dp
    },
    "severity_distribution": {
        "0": 0, "1": 0, "2": 0,        // int
        "3": 0, "null": 0              // int
    },
    "trend": [
        {
            "date":       "YYYY-MM-DD",
            "total":      0,           // int
            "drifted":    0,           // int
            "drift_rate": 0.0          // float, 3 dp
        }
    ]
}
```

Invariant: `sum(severity_distribution.values()) == total_records`.

`skipped_records` counts variance files that failed to parse as JSON — this is not an error condition; malformed records are silently skipped and the run still exits `0`. `records_without_timestamp` counts records anchored by file mtime rather than the `timestamp` field, for legacy records that pre-date it (see the `timestamp` note in the `variance-save` section above); a non-zero count means the trend's day placement for those records may be unreliable. When a `timestamp` *is* present, it is used as-is to anchor the record: a naive (offset-less) value is tagged UTC, but a value carrying an explicit non-UTC offset is not converted, so its trend-day placement reflects that offset rather than UTC.

Drift classification is severity-primary: `severity` of 1, 2, or 3 counts as drifted, `0` counts as clean, and a `null`/absent `severity` falls back to a prose check on the `variance` field (empty string or `"no variance"`, case-insensitively, counts as clean; any other non-empty text counts as drifted).

#### Example output (`--format json`)

```json
{
  "window": {
    "from": "2026-07-19T00:00:00+00:00",
    "to": "2026-07-23T00:00:00+00:00"
  },
  "total_records": 4,
  "skipped_records": 0,
  "records_without_timestamp": 0,
  "drift": {
    "drifted": 1,
    "clean": 3,
    "drift_rate": 0.25
  },
  "severity_distribution": {
    "0": 2,
    "1": 0,
    "2": 1,
    "3": 0,
    "null": 1
  },
  "trend": [
    {"date": "2026-07-19", "total": 0, "drifted": 0, "drift_rate": 0.0},
    {"date": "2026-07-20", "total": 1, "drifted": 0, "drift_rate": 0.0},
    {"date": "2026-07-21", "total": 2, "drifted": 1, "drift_rate": 0.5},
    {"date": "2026-07-22", "total": 1, "drifted": 0, "drift_rate": 0.0}
  ]
}
```

#### Example output (`--format text`)

```text
Drift report -- 2026-07-19 to 2026-07-23
  Sessions analyzed:  4
  Drifted:            1 / 4  (25%)
  Severity:           0:2  1:0  2:1  3:0  null:1

  Trend (drift rate by day):
    07-19  (no sessions)
    07-20                          0%  (0/1)
    07-21  ##########             50%  (1/2)
    07-22                          0%  (0/1)
```

Both samples were generated from the same four synthetic records over `--from 2026-07-19 --to 2026-07-23`.

#### Exit codes

| Code | Meaning | stderr |
|---|---|---|
| `0` | Success — JSON or text written to stdout | *(silent)* |
| `1` | Invalid range: `--from` is not strictly before `--to` | `drift-report: invalid range: --from must precede --to` |
| `1` | Range exceeds 366 days | `drift-report: window exceeds 366 days -- use a narrower range` |
| `1` | I/O error reading the variance directory | `drift-report: I/O error reading variance dir: <reason>` |

All three `1` cases are validated or raised before any output is written; stdout is empty on failure.

---

### `audit` — agent/skill inventory and hygiene report

```bash
python -m claude_prospector audit
```

Deterministically inventories all agents and skills visible in the effective
Claude Code configuration (custom and plugin-provided), then reports:

- **Name collisions** — agents or skills with identical names loaded from
  different sources
- **Jaccard semantic overlap** — pairs whose description tokens overlap above a
  configurable threshold, signalling potential duplicate capability
- **Tool-coupling mismatches** — agents declared without the tools they call,
  or with tools they never reference
- **Cache hygiene issues** — stale plugin cache entries that may shadow the
  live install

The subcommand is read-only — it never modifies files. Output is written to
stdout; pipe to a file or redirect as needed. The `/claude-prospector:claude-audit`
skill wraps this subcommand for conversational use inside Claude Code sessions.

### `config` — inspect configuration

```bash
python -m claude_prospector config --show
```

Prints current `config.json` contents, or `{}` when no config file exists. See [Configuration](#configuration) for full details.

## Migration

### v0.6.0 → v0.7.0 (Pattern W)

After upgrading to v0.7.0, open a new Claude Code session. A banner will prompt you to run `/setup-prospector`. This is a one-time action per machine.

If you previously installed `claude-prospector` into `~/.claude/.venv`, you can leave that install in place — Pattern W hooks always use the plugin-owned venv via an absolute path. To reclaim disk space you may `uv pip uninstall claude-prospector` from `~/.claude/.venv` after setup; this is optional.

### Pre-v0.2.0 CLI callers

The bare flag form **no longer works** after v0.2.0:

```bash
# REMOVED — will print help and exit 0, not run the dashboard
claude-prospector --format json

# CORRECT
claude-prospector dashboard --format json
```

Any script, skill, or CI step that invokes `claude-prospector` with bare flags (no subcommand) must be updated to use `claude-prospector dashboard [flags]`.

### Upgrading from v0.4.x (autoregen config)

If you previously ran `python -m claude_prospector config --enable-autoregen`, your old `config.json` is still readable via `--show`. Re-toggle via `/plugin reconfigure claude-prospector` to move to the managed setting. The old `config.json` file is not deleted.

## Internals

### Nested agent attribution

When Claude Code sessions dispatch sub-agents that themselves dispatch further sub-agents, `claude-prospector` traces the full depth and attributes tokens to the complete root-to-leaf chain rather than just the immediate leaf.

- **Data model.** Each `MessageRecord` carries an `agent_path: tuple[str, ...]` field (e.g. `("general-purpose", "project-planner", "Explore")`) and a parallel `agent_type: str` stored field. Both are populated at parse time; the parser enforces the invariant `agent_type == agent_path[-1]` when `agent_path` is non-empty. The two fields are kept in sync by the parser, not by the dataclass itself.

- **`by_agent` keys.** The aggregator's `by_agent` dict is keyed by the full path joined with U+2192 (`→`), for example `"general-purpose→project-planner→Explore"`. Depth-1 sessions produce single-segment keys identical to the pre-change shape.

- **Per-session `agents` list.** Each session's `agents` list contains only the deepest-leaf path per chain. Sibling chains that share a leaf name but differ in their ancestor are both kept. This rule preserves the dashboard JS's per-agent token apportionment, which divides session totals by `s.agents.length`.

- **Depth limit.** Path tuples may contain up to 10 segments total (`_MAX_AGENT_PATH_LENGTH = 10`). Beyond that, the parser emits a single `UserWarning` and stops descending; deeper messages are bucketed under the last walked ancestor.

- **Sanitization.** A literal `→` appearing inside an agent name is replaced with `﹖` (U+FE56) at parse time and a `UserWarning` fires. The sanitized name is used throughout.

- **Deferred.** Dashboard tree visualization (sunburst, indented tree, expand/collapse) is out of scope for the current release. The existing flat agent list in the dashboard JS receives path-keyed entries but no hierarchical rendering yet.

### State storage and local data

When running as a plugin, state is stored under `${CLAUDE_PLUGIN_DATA}` — the Anthropic-documented persistent state location that survives plugin updates. Outside the plugin host it falls back to `~/.claude/claude-prospector/` (override either with `CLAUDE_PROSPECTOR_BASE_DIR`; see [Environment variables](#environment-variables)).

Users upgrading from v0.4.0 get a one-time migration attempt: the first time `${CLAUDE_PLUGIN_DATA}` is resolved, if the legacy `~/.claude/claude-prospector/` directory exists and has content, its files are moved into `${CLAUDE_PLUGIN_DATA}` and the legacy directory is removed. Migration is **skipped** (legacy directory left in place) if `CLAUDE_PROSPECTOR_BASE_DIR` is set, or if `${CLAUDE_PLUGIN_DATA}` already exists and is non-empty. Migration can also **fail partway** — files are moved one at a time, so an I/O error mid-move can leave some files already relocated and others still in the legacy directory; the error is swallowed and logged to `hook.log`, and files may end up split across both locations. Verify both locations before deleting old data.

The table below lists everything `claude-prospector` writes under that base directory, and whether it can contain your prompt/message text. Each path can be overridden independently — see [Environment variables](#environment-variables) for `CLAUDE_PROSPECTOR_CONFIG`, `CLAUDE_PROSPECTOR_DASHBOARD`, `CLAUDE_PROSPECTOR_HOOK_LOG`, and `CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR`; the `dashboard` subcommand's `--output` flag and the `variance-save` subcommand's `--out` flag override a single invocation's output path without touching the environment:

| Path | Contents | Written by | Contains prompt text? |
|---|---|---|---|
| `dashboard.html` | Aggregated token/cost stats | `dashboard` subcommand, or the opt-in `dashboard-regen` Stop hook | No |
| `hook.log` | One diagnostic line, e.g. `skipped: no skills found in Agent prompt for <agent>`; truncated and overwritten on every hook run | All hooks | No — logs the target agent *name*, never prompt content |
| `config.json` | User settings (`project_exclude_patterns`, legacy `autoregen`) | `config` subcommand / manual edit | No |
| `skill-tracking/<YYYY-MM-DD>.jsonl` | Skill name, timestamp, session-id, and (for Agent dispatches) target agent name, for each `Skill`/`Agent` tool-use event | `skill-tracker` PreToolUse hook — runs automatically on every `Skill`/`Agent` tool call once setup is `VALID` | No — only the matched skill *name* is stored, never the surrounding prompt |
| `variance/<session-id>.json` | **Verbatim** first and subsequent user messages (`original_ask`, `prior_asks`) for the analyzed session, the file paths it edited, and an LLM-written variance judgment — or, when `variance-save` is run with `--redact-prompts`, `null`/`[]` in place of that text plus a `prompts_redacted: true` marker | `variance-save` subcommand — invoked only by the opt-in `/session-analysis` skill or a manual CLI call, **never automatically** | **Yes**, unless written with `--redact-prompts` |
| `setup-state.json` | Plugin version and venv path | `/setup-prospector` | No |

**`variance/<session-id>.json` is the only file that can store prompt content, and it is opt-in at two levels.** It is written exclusively when you (or the `/session-analysis` skill acting on your behalf) run `session-analysis` or `variance-save` for a specific session — see the [`variance-save` subcommand](#variance-save--persist-combined-audit--judgment) above for the exact schema. Within that, pass `--redact-prompts` to `variance-save` to keep the record's `original_ask`/`prior_asks` fields empty (`null`/`[]`) while still writing everything else (actions, variance judgment, severity, timestamp) — the record gains a `prompts_redacted: true` field so readers can tell redaction happened. Nothing else `claude-prospector` writes contains message text.

**Clearing local data.** Each of these files/directories is regenerated on demand and safe to delete on its own at any time. `cd` into your base directory first (the plugin-managed path, or `~/.claude/claude-prospector/` under the legacy layout — see above), then:

```bash
rm -rf variance/          # the prompt-bearing records
rm -rf skill-tracking/    # skill-name events (no prompt text)
rm -f  hook.log dashboard.html
```

These commands assume the default, unoverridden paths. If you've set any of the `CLAUDE_PROSPECTOR_*` path overrides above, `skill-tracking/`, `hook.log`, and `dashboard.html` may live elsewhere — adjust the paths (or target the overridden location directly) accordingly. `variance/` has no env-var override — it is always `<base_dir>/variance/` — though `variance-save --out` can place a single record anywhere.

Deleting `variance/` only shrinks `drift-report`'s aggregation window (fewer or zero records to summarize) — it never breaks other features. Deleting `skill-tracking/`, `hook.log`, or `dashboard.html` is likewise harmless; each is recreated the next time its triggering event occurs.

Do **not** `rm -rf` the whole base directory as a shortcut — under the plugin-managed path it also holds `venv/` (the Python environment `/setup-prospector` built) and `setup-state.json`; deleting those forces a full `/setup-prospector` re-run.

**Disabling.**

- `variance-save` and `/session-analysis` are opt-in by design — don't invoke them and no prompt text is ever written to disk. When you do invoke `variance-save`, pass `--redact-prompts` to keep the written record free of verbatim prompt text while still capturing the variance/severity judgment.
- `skill-tracker` — the only *automatic* hook that persists per-event records — has no dedicated on/off toggle today, and its gating is one-directional. **Before** `/setup-prospector` has ever completed successfully, skipping it keeps `skill-tracker` inactive — at the cost of every other feature (dashboard, usage-analysis), since none of them work without setup either. **After** setup has completed and the setup-state flag reads `VALID`, `skill-tracker` runs on every `Skill`/`Agent` tool call regardless of whether you run `/setup-prospector` again — there is no way to disable it alone while keeping the rest of the plugin active, and *not* re-running `/setup-prospector` does not retroactively turn it off (the flag only goes stale on a plugin-version bump, or breaks if the venv is later removed/corrupted — see [Troubleshooting](#troubleshooting)). Use `CLAUDE_PROSPECTOR_SKILL_TRACKING_DIR` if you want its (prompt-text-free) output redirected somewhere else.
- `dashboard-regen` (Stop hook) is opt-in and off by default — toggle via `/plugin reconfigure claude-prospector` (see [Configuration](#configuration)).

## Development

### Install for development

```bash
git clone https://github.com/glitchwerks/claude-prospector.git
cd claude-prospector
uv sync   # installs runtime + ruff + pytest; creates .venv with Python 3.12
```

Requires Python 3.12 (pinned via `.python-version`).

If `uv sync` creates the venv with the wrong interpreter (e.g. you have a newer Python on PATH), delete `.venv/` and re-run `uv sync`. The `.python-version` file pins Python 3.12 and `uv` will locate or download it automatically.

### Testing

```bash
pytest   # 358 tests, typically finishes in under 5 seconds
```

### Linting and formatting

```bash
ruff check .          # lint
ruff format .         # autoformat in-place
ruff format --check . # format gate (used in CI — exits non-zero on drift)
```

### CI

GitHub Actions runs on every PR and push to `main`:

- **lint** (Ubuntu): `ruff check .` + `ruff format --check .`
- **test** (Ubuntu + Windows, Python 3.10): `pytest`

Both jobs must be green before a PR can merge.

### Future enhancements

Issue #67 tracks making `claude plugin update` handle the Python venv refresh automatically, so that `/setup-prospector` would not need to be run manually after updates. Until that lands, re-run `/setup-prospector` after each plugin update when prompted by the SessionStart banner.

## Contributing

To release a new version, see [docs/release-process.md](docs/release-process.md).

## License

MIT — see [LICENSE](LICENSE).
