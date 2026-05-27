---
name: usage-analysis
description: >
  Use when the user asks an interpretive question about their Claude Code
  token spend — what's interesting, what's anomalous, what to change. This
  skill produces insights and questions; it does NOT enumerate top
  consumers (the dashboard does that).

  Use `usage-dashboard` for "show me the numbers." Use `claude-audit` for
  "audit my config overlap." Use this skill for "tell me what's interesting
  / what should I change."

  Trigger phrases: "am I close to my Claude limit", "how much Sonnet am I
  using", "where are my Claude tokens going", "what's eating my Claude
  budget", "why is my Claude spend so high", "what should I change about
  my Claude setup".
---

# Usage Analysis Skill

You are surfacing **insights and improvement suggestions** about the
user's Claude Code token spend that are not obvious from the dashboard at
a glance. Your output is observations + questions, not a stats rehash.

## Companion skills — route the user away when appropriate

| User wants | Skill |
| --- | --- |
| Show me my numbers / regenerate the dashboard | `usage-dashboard` |
| Audit my agent/skill config for overlap or conflicts | `claude-audit` |
| Tell me what's interesting / what should I change | **this skill** |

## Prerequisites

This skill invokes `python -m claude_prospector` under the hood. The
Python package must be installed in the environment Claude Code uses.
See the [README install steps](https://github.com/glitchwerks/claude-prospector#install-as-a-claude-code-plugin)
for the two-step install.

## Input — structured JSON, not the rendered dashboard

Get the structured payload directly from the CLI. Do **not** screen-scrape
the dashboard HTML.

```bash
python -m claude_prospector dashboard --format json --no-open
```

`--format json` writes the same `DATA` object the dashboard embeds, to
stdout. Progress lines go to stderr. Pipe through `jq` (or read into
memory) and reason over it.

Add `--window 7d` / `--window 5h` / `--from --to` to scope. Run multiple
windows if comparing — e.g. 7d vs. all-time to see whether a category is
growing or shrinking.

Skill-tracking events (passed vs. invoked) live in per-day JSONL files at:

- POSIX: `$HOME/.claude/claude-prospector/skill-tracking/<YYYY-MM-DD>.jsonl`
- Windows: `%USERPROFILE%\.claude\claude-prospector\skill-tracking\<YYYY-MM-DD>.jsonl`

Each line is `{"event": "skill_invoked"|"skill_passed", "skill": ..., ...}`.
Read these directly — they're the input for trigger-drift insights and are
not reflected at the same fidelity in the dashboard.

## Insight categories — what to look at

These categories are **harness-agnostic**. They reference data shapes the
parser emits regardless of which agents, skills, or routing topology the
user has installed. Do not assume any specific agent name (e.g.
`general-purpose`, `code-writer`), skill name, or dispatch pattern is
present.

1. **Trigger drift** — skills with `skill_passed` >> `skill_invoked`. The
   skill is being loaded into context but rarely actually firing — its
   triggers may be too narrow, or the user's prompts may have drifted
   away from them.

2. **Model imbalance vs. stated workflow** — one model dominating
   disproportionately. Surface the ratio; do not assert what "correct"
   looks like — the user's workflow dictates the right mix.

3. **Agent cost-per-session outliers** — flag any agent whose
   tokens/session is more than ~2σ above the cohort mean. Name the agent
   generically; the user knows what their agents are for.

4. **Single-session outliers** — any one session consuming >10% of the
   windowed total. Worth surfacing because it usually means an
   orchestration anomaly (runaway loop, accidental long context, etc.).

5. **Trend inflections** — daily or weekly deltas that change sign, or
   exceed ~30% week-over-week. Note the direction and magnitude.

6. **Cross-skill correlation (optional)** — if `claude-audit` findings
   are available in the same conversation, correlate them with cost:
   a high-cost agent that also has an audit-flagged tool-coupling gap is
   worth a focused mention.

If none of categories 1-6 trips a meaningful threshold, **say so
plainly** — silence is a valid finding, and inventing concern wastes the
user's time.

## Suggestion format — how to deliver findings

Lead with the **2-3 most consequential insights**. For each, three lines:

```
Observation:   <one sentence, with the data citation>
Implication:   <what this might mean for the user's workflow>
Question:      <ask the user about THEIR intent — don't assert>
```

Rules:

- **No top-consumer enumeration.** Top-N tables belong in the dashboard.
  If the user wants the numbers, they'll open the dashboard.
- **No prescriptive advice** ("you should switch X to Haiku") — pose it
  as "was that the role you intended for X?" The plugin author doesn't
  know the user's harness or intent; the user does.
- **Cite the data** — point at a session ID, a daily bucket, a JSON key,
  or the date range you queried. Numbers without a citation are
  unverifiable.
- **Use the structured CLI output, not the HTML** — if you find yourself
  reaching for `Read` on `dashboard.html`, you've taken a wrong turn.
  Use `--format json`.

## Worked example (illustration only — your output will differ)

```
Observation:  Skill `<X>` was passed in 42 sessions over the last 7 days
              but invoked in only 3 (skill-tracking/2026-05-20..26).
Implication:  Either the trigger phrases are too narrow for how you're
              actually prompting, or the skill is loaded but redundant.
Question:     Do you remember invoking `<X>` recently? If not, want to
              tighten its triggers or unload it?
```

This is **one** insight at the right shape — not a section title to fill
with subbullets.

## Triggers we deliberately do not claim

The following phrases were present in the original private skill but are excluded here because
they are too generic for a public marketplace skill and would cause false-positive activations
in unrelated contexts:

| Phrase                 | Why excluded                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| `show usage`           | Matches any CLI tool or dashboard; not specific to Claude Code token accounting.                 |
| `show my token usage`  | Broad — applies to any LLM or API context, not specifically Claude Code billing buckets.         |
| `check my usage`       | Ambiguous — could refer to disk usage, API rate limits, quota on any service.                    |
| `how much am I using`  | No Claude-specific signal; triggers on resource questions of all kinds.                          |
| `how much have I used` | Same problem as above; past-tense variant with no additional specificity.                        |
| `usage breakdown`      | Common analytics phrase; would steal traffic from project-specific dashboard or reporting tools. |
| `usage report`         | Same as above; too broad for a specialised skill.                                                |
| `optimize my usage`    | Could apply to any resource optimization context — storage, bandwidth, API calls, etc.           |

Do not re-add these phrases to the `description:` frontmatter. If a user types one of these
and the context makes it clear they mean Claude Code token usage, the skill body's language
about billing buckets and `claude_prospector` will guide the response correctly once
activated by a sharper trigger phrase.
