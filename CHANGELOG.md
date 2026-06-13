# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.11.1] - 2026-06-13

### Fixed

- **`setup-prospector` Step 1 named the wrong default plugin-data slug.**
  The slug was incorrectly rendered as `claude-prospector-claude-prospector`;
  corrected to `<plugin>-<marketplace>` = `claude-prospector-glitchwerks`.
  Also hardened `CLAUDE_PLUGIN_DATA` handling: if the environment variable
  points at a directory whose basename does not start with `claude-prospector-`,
  the computed default slug is used instead of trusting the foreign path
  (#209, closes #209, PR #230).
- **`derive_project_name` now folds git-worktree sessions into their owner
  repo.** Sessions whose `cwd` matches `<repo>/.worktrees/<branch>` or
  `<repo>/.claude/worktrees/<name>` are attributed to the owner repository
  instead of appearing as separate dashboard projects (PR #231, closes #229).
- **Documented the accepted best-effort limitation of the no-`cwd` worktree
  fallback.** When no `cwd` is recorded, slug-only heuristics may truncate
  multi-token repo names and lose path-boundary information; this is a known
  limitation and is now noted in the relevant docstring and docs
  (PR #234, closes #232).

## [0.11.0] - 2026-06-13

### Added

- **`session-audit` CLI subcommand** (`python -m claude_prospector session-audit
  --path <transcript.jsonl>`) — deterministic, zero-LLM-cost extractor that
  reads a Claude Code session transcript and emits structured
  `original_ask / prior_asks / actions` data. Supersedes the abandoned
  Stop-hook self-audit spike (#129). `--session-id` lookup and
  `--format text` output also supported (#212).
- **`session-analysis` skill** — LLM-assisted interpretive complement to
  `session-audit`. Runs inside the current Claude session to produce
  `variance / not_done / severity` judgments and persists a combined record
  via `variance-save` for downstream drift aggregation (#213).
- **`drift-report` CLI subcommand** (`python -m claude_prospector drift-report`)
  — reads accumulated `variance/<id>.json` records and reports drift
  frequency, severity distribution, and a per-day trend over a configurable
  window (`--window` or `--from`/`--to`). Implements the drift-aggregation
  spec (Phase 1 of #219; #220).
- **Automated GitHub Release creation** in `release.yml` (#214). A new
  `github-release` workflow job runs after `publish-pypi` succeeds on
  stable tags (same `!contains(-rc/-alpha/-beta)` guard). It extracts the
  matching `## [X.Y.Z]` section from `CHANGELOG.md` via
  `scripts/extract-changelog-section.py` and creates the GitHub Release via
  `gh release create --verify-tag --latest`. Pre-release tags continue to
  publish to TestPyPI only and do not produce a GitHub Release.
- `scripts/extract-changelog-section.py` — helper script that extracts a
  single version's section from a Keep-a-Changelog formatted file. Accepts
  `<version>` (with or without a leading `v`) and an optional
  `<changelog-path>`; exits non-zero when the version is absent. Used by the
  `github-release` workflow job; covered by unit tests in
  `tests/unit/test_extract_changelog_section.py`.

### Changed

- **`timestamp` field added to variance records** (`variance/<id>.json`).
  Derived from the earliest raw transcript entry (with mtime fallback for
  pre-field records), giving the forthcoming `drift-report` aggregator a
  reliable time anchor. Phase 0 of #217 (#218).
- **`model_short` recognizes the `fable` model tier.** Token usage for Fable
  model variants (e.g. `claude-fable-1-0`) now groups under a dedicated
  `fable` tier instead of falling through to the raw model-ID string in
  aggregation output (#225).
- `docs/release-process.md` updated with a post-release checklist, a revised
  step 5 (verify all four workflow jobs), a new step 5a (verify/fallback for
  GitHub Release), an updated Quick Reference Card, and a new Footguns entry
  documenting the v0.8.2–v0.10.0 incident where GitHub Releases were silently
  skipped (#214).
- `docs/spikes/2026-05-19-self-audit-spike.md` salvaged from the retired
  `self-audit-spike-129` branch, reframed as concluded/cancelled exploratory
  work retained for historical record. The spike's elicitation evidence (5/5
  session shapes met the rubric) is preserved; the Stop-hook mechanism was
  rejected on cost/UX grounds and superseded by `session-audit` (#211).
- `docs/superpowers/specs/drift-aggregation.md` finalized after adversarial
  inquisitor review. Four blocking errors corrected (timestamp anchor location,
  raw-dict data path, `_parse_window` return type, stale sequencing note) and
  verified against the producer code (#216).
- `CLAUDE.md § CI gates` updated to spell out both Lint commands explicitly:
  `uv run ruff check .` and `uv run ruff format --check .` (#227).

## [0.10.0] - 2026-05-30

### Added

- Added `audit` subcommand (`python -m claude_prospector audit`) that
  deterministically inventories agents/skills, detects name collisions,
  computes Jaccard semantic overlaps, detects tool-coupling mismatches,
  and flags cache hygiene issues (closes #191).
- **cwd-first project names** in the dashboard: the leaf directory name
  (e.g. `claude-prospector`) is derived from the `cwd` field recorded
  in the session when available, falling back to the decoded directory
  slug. Full decoded path is shown on hover. A `project_exclude_patterns`
  list in `config.json` lets you hide noise directories (Electron
  internals, Warp worktrees, etc.) from the project breakdown by
  case-sensitive substring match against the session's full path
  (#203, closes #205).

### Changed

- Refocused `usage-analysis` skill on insights and improvement
  suggestions, dropping content that duplicated `usage-dashboard`
  (top-consumer enumeration, dashboard regeneration mechanics, HTML
  scraping). The skill now consumes structured `--format json` output
  from the CLI, organizes findings around six harness-agnostic insight
  categories, and uses an Observation / Implication / Question delivery
  format that defers to the user's intent rather than prescribing
  changes (closes #193).

### Fixed

- **Today/daily activity bucketed by local timezone instead of UTC**
  (#197, closes #199). The dashboard's "today" bucket and per-day
  activity bars previously used UTC midnight as the day boundary,
  causing sessions that ran after midnight UTC but before local midnight
  to appear on the wrong day.
- **Movers tab distinguishes "resumed" from "new" sessions** (#200,
  closes #202). The recent-movers pane previously classified all
  sessions that appeared in the current window as "new". Sessions that
  were already present in the prior window are now marked "resumed" so
  the pane reflects only genuinely new activity.
- **`dashboard --output` creates parent directories and defaults to the
  plugin data location** (#201, closes #204). Passing an `--output`
  path whose parent directory did not yet exist previously raised an
  error. Parent directories are now created automatically. When
  `--output` is omitted, the dashboard is written to
  `${CLAUDE_PLUGIN_DATA}/dashboard.html` rather than the current
  working directory.
- **Full-path hover tooltip extended to all project-name surfaces**
  (#206, closes #207). The decoded-path tooltip introduced with
  cwd-first project names was only wired to the byProject card; it now
  appears on every surface that displays a project name (session
  drill-down rows, Movers entries, etc.).

## [0.9.1] - 2026-05-26

### Fixed

- **Dashboard `--window` no longer filters out prior-period data needed for week-over-week comparison panes** (#188). The `dashboard` subcommand previously defaulted to `--window 7d`, which made the Economy v1 dashboard's recent-movers / burn-rate-trendline / "Why did total tokens change?" panes effectively unusable because the aggregator pre-dropped everything older than 7 days. Default is now "no window filter; aggregate the full session history". `--window` remains accepted as an explicit opt-in flag for users who want a scoped dashboard.

[0.11.1]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.11.1
[0.11.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.11.0
[0.10.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.10.0
[0.9.1]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.9.1

## [0.9.0] - 2026-05-26

### Added

- **Economy v1 dashboard** (#144) — a three-tab dashboard shell (Overview / Breakdown / Advanced) replaces the single-view layout. (#170, #171)
  - **Overview** (`economics-basic.js`) — top-line spend with "Where your tokens went" agent attribution.
  - **Breakdown** (`layout-b-diag.js`) — cumulative spend, per-day histogram, top sessions, recent movers.
  - **Advanced** (`economics.js`) — Goodhart decomposition, burn-rate projection, full diagnostic surface.
  - Chart.js + chartjs-chart-treemap are vendored under `src/claude_prospector/static/` and shipped in the wheel via `[tool.setuptools.package-data]`.
- **Per-token-type breakdowns** in `by_day` and `sessions` aggregator output (#166) — input / output / cache_read / cache_creation tokens are reported separately, enabling the dashboard's per-component cost lines.
- **Per-agent token attribution** on session records (#174, fixed in #175). The aggregator now emits `agent_tokens: dict[str, int]` per session, which fixes a client-side over-attribution bug where the dashboard apportioned `session.total_tokens / session.agents.length` and reported sub-agent invocations (e.g. `ops` as a Haiku runner) at billions of tokens.

### Fixed

- **`userConfig.autoregen` missing schema default** (#149, fixed in #150). Added `"default": false` to the `autoregen` field in `.claude-plugin/plugin.json` so the plugin manager has an explicit default and does not prompt unexpectedly or treat a missing value as true.
- **Goodhart decomposition mixed numeric notation** (#173) — some panes showed raw token counts while siblings used `k`/`M`/`B` suffixes; unified through `CP.fmtTokens`.
- **Burn-rate chart vertically compressed** (#173) — raised the chart height so the 7-day cumulative projection is legible.
- **Negative number formatting / active-days computation / pill hover state / SVG sizing** (#176, fixed in #177) — user-provided JS polish bundle applied as a drop-in.
- **`msgs/session` sparkline rendered flat** (#179, fixed in #180) — the aggregator was not plumbing per-day `session_count`, so the sparkline divided messages by total sessions instead of per-day session counts.

### Changed

- **Removed the skill-adoption quadrant pane** from the Breakdown view (#185, removed in #186). Three iterative fix attempts (#173 clamp → #181 re-classify → #183 revert) produced three different broken layouts. Rather than ship a known-flaky chart, the quadrant is dropped from 0.9.0 and re-add work is tracked in **#184** (four design options enumerated: fixed-percentile thresholds, log axes, two-panel small-multiples, density heatmap).
- **`_base_dir` resolution refactored** to a dataclass (#159, refactored in #164) — internal-only; no behavior change.

### Notes

- Release runbook (`docs/release-process.md`, #141) and project `CLAUDE.md` (#143) were added in the 0.9.0 cycle but are documentation-only and ship outside the user-facing surface.

[0.9.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.9.0

## [0.8.2] - 2026-05-20

### Fixed

- **Wheel install: `TemplateNotFound` crash on `dashboard` command** (#138).
  The renderer used `jinja2.FileSystemLoader` pointed at a
  `Path(__file__).parent`-relative path.  In an editable / source-tree
  install this works because the file is on disk at the expected location.
  In a wheel install the path resolves to the site-packages directory,
  where `templates/` does not exist as a loose filesystem subtree.
  Fix: replace `FileSystemLoader` with `PackageLoader("claude_prospector",
  "templates")`, which resolves the template through Python's package
  resource system (`importlib.resources`) and works correctly for both
  editable and wheel installs.
- Added a `wheel-smoke` CI job to `release.yml` that installs the built
  wheel into a fresh venv and runs `python -m claude_prospector dashboard`
  against a fixture before publishing.  This gate would have caught the
  0.8.0/0.8.1 regression at release time.

## [0.8.1] - 2026-05-19

### Changed

- Dashboard template replaced with a new visual model: refreshed layout,
  panel structure, and styling. The renderer contract is unchanged — same
  `data_json` / `limits_json` / `generated_at` Jinja bindings, no API
  impact. (#130, #131)

## [0.8.0] - 2026-05-19

### Added

- `claude-audit` skill: audits your effective Claude Code configuration
  (custom + plugin-provided agents and skills) and produces a structured
  overlap / conflict report with keep / modify / drop recommendations
  scoped to the project's stated objectives. Activates via
  `/claude-prospector:claude-audit` or natural-language phrases like
  "audit my claude config", "find overlap in my agents". Read-only —
  produces a report only; does not modify any files. (#123)

### Changed

- Plugin and PyPI `description:` fields reframed from "token usage
  analyzer" to "Claude Code efficiency and hygiene toolkit" to reflect
  the broader scope (cost + config-hygiene angles). README "Why" section
  updated with a per-skill responsibility table. Plugin keywords
  expanded with `audit` + `config-hygiene`. (#123)

### Upgrade notes

- If you had `~/.claude/skills/claude-audit/` as a user-global skill
  before upgrading, remove it after this version installs. Keeping both
  copies causes duplicate activation on the same trigger phrases.

## [0.7.1] - 2026-05-18

### Changed

- Rewrote `description:` frontmatter for both plugin skills
  (`usage-analysis`, `usage-dashboard`) to use "Use when..." activation
  framing with explicit "Do NOT use ... (use other skill instead)"
  boundaries. Trigger phrases now carry `Claude` / `prospector` / `token`
  disambiguators to prevent false positives in cloud-billing or
  API-quota contexts. (#119, closes #101)
- README audited for correctness against v0.7.0 code and restructured
  into 12 sections; "Why" section rewritten to acknowledge Claude
  Code's built-in `/usage` command and clarify what `claude-prospector`
  adds on top. (#118)

### Removed

- Empty `commands/` folder (deprecated surface — skills replaced
  commands in v0.6.0). (#117)

## [0.7.0] - 2026-05-18

### Added

- `/setup-prospector` skill: materialises a plugin-owned Python venv at
  `${CLAUDE_PLUGIN_DATA}/venv/` and writes a setup-state flag. Required
  once after install or after a plugin update.
- `SessionStart` hook (`hooks/check-prospector-setup.py`): surfaces a
  banner when setup is required and runs a per-session import probe to
  detect venv corruption.
- `hooks/lib/setup_state.py`: shared deterministic helper for flag I/O,
  version comparison, and venv-python path resolution.
- CI: `skill-smoke-{ubuntu,windows}` jobs validate the full setup
  pipeline on every PR against real Python 3.10 and real pip.

### Changed

- `hooks/dashboard-regen.py` no longer guesses the venv root via
  `Path(sys.executable).parent.parent.parent`. Both the version-check
  subprocess (`:506-514`) and the dashboard regen subprocess (`:543-560`)
  now use the absolute path recorded in the setup-state flag.
- `hooks/skill-tracker.py` now short-circuits silently when the
  setup-state flag is not VALID, deferring to the SessionStart banner
  for user guidance.
- `claude-prospector` is now published to PyPI. The setup skill installs
  from PyPI by default; `CLAUDE_PROSPECTOR_PIP_SPEC` allows installing
  from a local checkout for development.

### Migration from v0.6.0

After upgrading to v0.7.0, open a new Claude Code session. A
SessionStart banner will prompt you to run `/setup-prospector`. This is
a one-time action per machine per major version.

If you previously installed `claude-prospector` into `~/.claude/.venv`
(the user-managed venv approach), you can leave that install in place —
Pattern W's hooks always spawn the plugin-owned venv via an absolute
path and will not pick up the legacy install. To reclaim disk, you may
`uv pip uninstall claude-prospector` from `~/.claude/.venv` after
Pattern W is working; this is optional and unrelated to plugin operation.

The `${user_config.autoregen}` setting is preserved across the upgrade.
The legacy `config.json` migration mechanism added in v0.6.0 continues
to function unchanged.

## [0.7.0rc1] - 2026-05-18

### Added

- TestPyPI rehearsal of the PyPI publish workflow shipped in #109. No functional changes — this release-candidate validates the OIDC trusted-publisher + tag-routing wiring end-to-end before the real `v0.7.0` ships Pattern W adoption (#107). (#111)

[0.7.0rc1]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.7.0-rc1

## [0.6.0] - 2026-05-17

### Changed

- **Breaking — user-config mechanism:** the `autoregen` setting is now declared in `plugin.json` under the `userConfig` block and toggled through the plugin manager (`/plugin reconfigure claude-prospector` or the install-time prompt), per [Anthropic's documented convention](https://code.claude.com/docs/en/plugins-reference#user-configuration). The `Stop` hook receives the value via `--autoregen "${user_config.autoregen}"` and parses truthiness in Python (`true` / `1` / `yes` case-insensitive). (#99, #100)
- **Breaking — CLI surface:** `python -m claude_prospector config` is now read-only (`--show`). The mutation flags `--enable-autoregen` and `--disable-autoregen` are removed — their job belongs to the plugin manager now.
- **Behavioral break for existing users:** if you had `autoregen: true` in the legacy `${CLAUDE_PLUGIN_DATA}/config.json`, autoregen will stop firing after upgrading until you re-toggle it through the plugin manager. The legacy file is preserved (not deleted) so you can consult your previous state.

### Added

- One-time `[migration]` notice written to `hook.log` when the legacy `config.json` is detected, advising users to re-toggle through the plugin manager. A sentinel file (`config.json.migrated-notice`) suppresses duplicate notices. (#100)

[0.6.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.6.0

## [0.5.0] - 2026-05-17

### Changed

- State-storage path resolution now uses a three-tier `base_dir()` lookup: `CLAUDE_PROSPECTOR_BASE_DIR` (explicit override) → `CLAUDE_PLUGIN_DATA` (Anthropic plugin state dir, populated by Claude Code at plugin load) → legacy `~/.claude/claude-prospector/` (fallback). Both hook scripts replicate the resolver inline to remain stdlib-only. (#96)

### Added

- One-time auto-migration: when `CLAUDE_PLUGIN_DATA` is set and the legacy `~/.claude/claude-prospector/` directory has content while the new location is empty, `paths.base_dir()` moves the contents via `shutil.move` and removes the legacy dir. Idempotent (skipped if new dir is non-empty); failures are logged to `hook.log` with a `[migration]` prefix and never crash the run. (#96)

[0.5.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.5.0

## [0.4.0] - 2026-05-16

### Added

- `skills/usage-dashboard/SKILL.md` — bare dashboard-regeneration sibling to `usage-analysis`, triggered by phrases like "regenerate the dashboard". (Originally landed as a `/usage-dashboard` slash command in #80, then ported to a skill in #92 before the v0.4.0 tag.)
- `hooks/skill-tracker.py` PreToolUse hook with per-day JSONL rotation under `~/.claude/claude-prospector/skill-tracking/<YYYY-MM-DD>.jsonl` — caps unbounded file growth, eliminates concurrent-append contention, and enforces a 90-day retention window (#84).
- `hooks/dashboard-regen.py` Stop hook that regenerates the usage dashboard automatically after each session, with opt-in via `{"autoregen": true}` in `config.json` (#90).
- Three failure HTML pages for the Stop hook covering missing Python interpreter, version mismatch, and regen failure (#90).
- `config` CLI subcommand (`--enable-autoregen` / `--disable-autoregen` / `--show`) for managing hook settings (#90).
- `--version` flag to the CLI (#90).
- `claude_prospector/paths.py` centralizing all persistent-state path resolution (#90).
- Plugin manifest scaffolding: `.claude-plugin/plugin.json`, `commands/`, `skills/`, and `hooks/` directories (#66).
- `skills/usage-analysis/SKILL.md` — conversational token-usage analysis ported into the plugin with trigger-phrase prune (6 Claude-Code-specific phrases retained) (#78).
- All persistent plugin state now consolidated under `~/.claude/claude-prospector/` (`config.json`, `dashboard.html`, `skill-tracking/`, `hook.log`) — was previously scattered across `~/.claude/` (#82, updated in #85).

### Changed

- **Breaking:** Python package renamed from `claude_usage` to `claude_prospector` — any code importing the old name must be updated (#62).
- Plugin description updated to "Claude Code token usage analyzer with optimization recommendations" (#69).
- README restructured so plugin installation leads and the Python-module CLI is demoted to a Development section (#75).
- `skill-tracker.py` reader retains a one-version transitional fallback for the legacy flat `~/.claude/skill-tracking.jsonl` to ease migration (#84).

### Removed

- Unused `pyyaml` runtime dependency (#58).

[0.4.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.4.0
