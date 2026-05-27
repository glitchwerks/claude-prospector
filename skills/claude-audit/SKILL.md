---
name: claude-audit
description: >
  Audit a project's effective Claude Code configuration — custom and plugin-provided agents and
  skills — and produce a structured overlap/conflict report with keep / modify / drop
  recommendations scoped to the project's stated objectives. Trigger this skill whenever the
  user types `/claude-audit`, asks to "audit my claude config", "find overlap in my agents",
  "check for skill conflicts", "are any of my agents duplicates", "what's redundant in my
  setup", or any similar request to review the agent/skill surface for the current project.
  Also trigger after a fresh plugin install when the user wants to verify nothing new collides
  with what's already there.
context-switch: false
---

# Claude Audit Skill

Produce a deterministic overlap/conflict report for the project's effective Claude Code
configuration. The audit considers user-scope (`~/.claude/`), project-scope
(`<project>/.claude/`), and plugin-provided sources together — because that is what the agent
actually loads at runtime.

The output is a single markdown report. The skill itself does **not** modify any files. All
recommendations are presented to the user; they decide what to change.

---

## Step 1: Discover the project objective

Before evaluating overlaps, read the project's `CLAUDE.md` (and any `README.md`) at the repo
root to understand what the project does. Specific things to extract:

- **Domain** — web app, infra, mobile, ML, mod development, etc.
- **Languages / frameworks** — informs which language skills are relevant
- **Workflows codified in CLAUDE.md** — issue tracking, PR conventions, branching, testing

Recommendations later are scoped to these. A `python` skill is not "redundant" just because
the project also uses TypeScript — it might still be load-bearing for tooling scripts.

If no project-level `CLAUDE.md` exists, fall back to the user-level `~/.claude/CLAUDE.md` and
note that the audit is using the user-scope objective only.

---

## Steps 2–5: Deterministic inventory and analysis

Run the built-in CLI subcommand and capture its markdown output:

```bash
python -m claude_prospector audit --project-dir <project-root>
```

This single command covers all four deterministic steps:

- **Step 2 — Inventory**: walks user-scope (`~/.claude/agents/`,
  `~/.claude/skills/*/SKILL.md`), project-scope (`.claude/agents/`,
  `.claude/skills/*/SKILL.md`), the plugin cache (latest version per
  `(marketplace, plugin)` only), and Windows Claude Desktop
  `~/AppData/Roaming/Claude/…/skills-plugin/` if present.
- **Step 3 — Direct name collisions**: groups all items by `(_type, name)`;
  any group with more than one entry is a collision.
- **Step 4 — Semantic overlaps**: computes bigram-Jaccard similarity on
  description text for same-type pairs; flags pairs with Jaccard ≥ 0.5.
- **Step 5 — Tool-coupling concerns**: scans each skill body for `mcp__*`
  mentions and `PowerShell`/`Bash` references; cross-references against
  each agent's `tools:` frontmatter and warns on mismatches.

The command also reports **cache-hygiene findings**: stray `temp_git_*`
clone leftovers and plugin names duplicated across multiple marketplace
directories.

Use `--format json` for machine-readable output with keys `inventory`,
`collisions`, `overlaps`, `tool_coupling`, and `cache_hygiene`.

---

## Step 6: Render the report

Produce a single markdown document with these sections, in order:

```markdown
# Claude Config Audit — <project name or "user-scope only">

## Project objective

<one paragraph paraphrased from the project CLAUDE.md, or "User-scope audit — no project CLAUDE.md found.">

## Inventory

- **Custom agents**: N (`name1`, `name2`, ...)
- **Custom skills**: N (`name1`, ...)
- **Plugin agents**: N from M plugins
- **Plugin skills**: N from M plugins
- **Effective total exposed to runtime**: N agents, M skills

## Direct name collisions

| Name            | Sources                          | Descriptions diverge? | Tools diverge? | Recommendation                       |
| --------------- | -------------------------------- | --------------------- | -------------- | ------------------------------------ |
| `code-reviewer` | custom, superpowers, feature-dev | No (near-identical)   | Yes            | Keep custom; disable plugin variants |

## Semantic overlaps

| Pair                                     | Jaccard | Verdict                                       | Recommendation                                   |
| ---------------------------------------- | ------- | --------------------------------------------- | ------------------------------------------------ |
| `git` (custom) ↔ `anthropic-skills:git` | 0.92    | True duplicate with project-specific addendum | Extract addendum to dedicated skill, drop custom |

## Tool-coupling concerns

| Agent         | Skill passed in | Missing tool                   | Recommendation                                                                  |
| ------------- | --------------- | ------------------------------ | ------------------------------------------------------------------------------- |
| `code-writer` | `powershell`    | `PowerShell` (only has `Bash`) | Translate guidance to POSIX in delegation, or pass to agent that has PowerShell |

## Recommendations summary

| Item                      | Action                | Priority | Rationale                   |
| ------------------------- | --------------------- | -------- | --------------------------- |
| Drop `feature-dev` plugin | uninstall via /plugin | high     | 3 overlap items in one move |

...
```

Order recommendations by **leverage** — a single action that resolves multiple overlaps
should rank above a single-item fix. Where the user has stated objectives in their CLAUDE.md,
mark recommendations that conflict with those objectives as "verify with user before
acting" rather than asserting them.

---

## Step 7: Offer follow-ups

After delivering the report, ask the user:

1. Whether to open GitHub Issues for each "drop" / "modify" recommendation (using the
   project's issue tracker per CLAUDE.md conventions)
2. Whether to create a Milestone grouping them, if there are 3+ recommendations
3. Whether to start on any specific recommendation now

Do **not** start making changes without explicit user confirmation. This skill is read-only
audit + recommendation; modifications are tracked separately.

---

## Reference

### Why "effective" config, not just custom?

A user might think "my config is fine, I only have 8 custom agents." But what loads at
runtime includes ~50 plugin skills and ~5 plugin agents. Overlaps appear at the boundary
between custom and plugin, and that boundary is invisible if you only audit one side.

### Why scope to project objective?

The same set of skills can be over-broad for one project and under-broad for another. A
`python` skill is essential in a Python repo and dead weight in a pure-Rust repo. The audit
should prefer keeping skills the project plausibly needs and dropping ones it does not —
which requires knowing what the project does.

### Related skills

- `superpowers:writing-skills` — for authoring new skills if the audit recommends extracting
  one
- `claude-md-management:claude-md-improver` — for the CLAUDE.md side of the same hygiene work
- `claude-prospector:usage-analysis` — for the cost-side view (which skills/agents are actually consumed)

## Long-Form Artifact Discipline

Audit reports are routinely 50–200 lines once every agent and skill is enumerated with a keep / modify / drop recommendation. Save the full report to `<repo>/.tmp/<YYYY-MM-DD>-claude-audit.md` and return a short chat reply listing:

1. **Inventory totals** — N agents and M skills audited (custom + plugin combined).
2. **Disposition counts** — keep / modify / drop tallies.
3. **Top 2-3 most consequential overlaps or conflicts** — typically direct name collisions or high-Jaccard semantic duplicates that resolve multiple items in one action.
4. **The file path** in backticks as the hand-off.

Do NOT paste the full report body inline — the file is the artifact, the chat reply is the pointer. The user opens the file for the full keep/modify/drop tables; the reply surfaces only what shapes their next decision.
