---
name: session-analysis
description: >
  Use when the user wants a judgment-level read on whether a Claude Code
  session stayed on task — did the agent do what was originally asked, and
  what did it acknowledge skipping. This is the interpretive (LLM) complement
  to the deterministic `session-audit` CLI: 1a extracts ask-vs-done for free;
  this skill adds the `Variance` and `What was NOT done` judgment that a parser
  can't compute, then persists a combined record for drift analysis.

  Cost: ~1-3k tokens of the current session, paid only when invoked. Opt-in by
  design — run it selectively, not on every session. Best run in a Sonnet (or
  stronger) session; the judgment quality depends on it.

  Use `session-audit` (CLI) for the free deterministic ask/actions extract.
  Use `usage-analysis` for token-spend insights. Use `claude-audit` for
  agent/skill config overlap. Use THIS skill for "did this session drift from
  what I asked".

  Trigger phrases: "/session-analysis", "did this session stay on task",
  "analyze session drift", "did the agent do what I asked", "what did this
  session skip", "variance analysis for session", "audit this session for
  drift", "check session <id> for variance".
---

# Session Analysis Skill (1b)

You are producing the **judgment** half of session drift-detection: given a
session's deterministic ask-vs-done extract (from 1a), assess whether the
agent stayed on task and what it acknowledged leaving undone — then persist a
combined record. This is interpretive work; a deterministic parser cannot do
it, which is exactly why it costs LLM tokens and is opt-in.

## Prerequisites

This skill drives the `claude_prospector` CLI. The package must be installed
in the environment Claude Code uses — see the
[README install steps](https://github.com/glitchwerks/claude-prospector#install-as-a-claude-code-plugin).

## Step 1 — Identify the target session

The session-id (or transcript path) is `` if provided.

- If `` is a session-id, use it directly.
- If `` is empty, find the most recent transcript for the current
  project under `~/.claude/projects/<encoded-cwd>/*.jsonl` (newest mtime) and
  **confirm the session-id with the user before spending tokens** — variance
  analysis is opt-in, don't guess silently.

## Step 2 — Load the deterministic extract (free, 1a)

```bash
python -m claude_prospector session-audit --session-id <id> --format json
```

This returns `{original_ask, prior_asks, actions}`. `original_ask` is the
authoritative first ask; `prior_asks` are later distinct asks in the session;
`actions` are the Edit/Write/NotebookEdit file paths. Reason over this — it is
your ground truth for "what was asked" and "what was changed".

For richer context (reasoning, tool failures, what the agent *said* it was
doing), also read the transcript itself at the resolved
`~/.claude/projects/<…>/<id>.jsonl`. Use it to judge intent, not to recompute
the deterministic fields.

## Step 3 — Form the judgment

Assess two fields against `original_ask` (+ `prior_asks` for multi-task
sessions):

- **`variance`** — did the agent stay on the original ask? Note scope creep,
  approach pivots, or drift onto a later ask at the expense of the first.
  Cite specifics (a file in `actions` unrelated to the ask; a pivot point in
  the transcript). If it stayed on task, say so plainly — "no variance" is a
  valid, useful finding.
- **`not_done`** — what did the agent acknowledge skipping or defer? Prefer
  the agent's own admissions in the transcript over your speculation. If
  nothing was skipped, say so.

Optionally assign **`severity`** (integer 0-3): 0 = on task, 1 = minor drift,
2 = notable unrequested scope or skipped ask, 3 = the session largely did not
do what was asked. Omit (null) if you can't justify a number.

Be evidence-bound: every claim cites a file path, a `prior_asks` entry, or a
transcript moment. Do not invent drift to fill the field.

## Step 4 — Persist the combined record

Write the judgment to a temp JSON file (prose is multi-line; don't fight shell
escaping), then call `variance-save`. It re-loads 1a internally and writes the
combined `{1a fields + your judgment}` to `<data>/variance/<id>.json`:

```bash
# judgment.json: {"variance": "...", "not_done": "...", "severity": <int|null>}
python -m claude_prospector variance-save --session-id <id> --judgment-file judgment.json
```

`variance-save` finds the transcript under `~/.claude` and writes output under
the plugin data dir by default — no extra flags needed. It prints the written
path; surface that to the user.

## Step 5 — Report

Give the user a short variance report (NOT a JSON dump):

```
Session <id> — variance: <one-line verdict, severity if assigned>
  Asked:    <original_ask, trimmed>
  Variance: <the judgment, with its citation>
  Skipped:  <not_done, with its citation>
  Saved:    <path printed by variance-save>
```

## When to run (and not)

- **Run it** on a session you suspect drifted, a long multi-task session, or
  one flagged by `prior_asks.length > 0`. Selective use is the whole cost
  argument — 1a+1b beats the abandoned always-on hook only when 1b runs on a
  minority of sessions.
- **Don't** auto-run it on every session — that re-introduces the per-session
  cost this design exists to avoid.
