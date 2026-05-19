# Self-Audit Stop Hook — Spike Methodology

**Date:** 2026-05-19
**Issue:** [#129](https://github.com/glitchwerks/claude-prospector/issues/129)
**Parent:** [#63](https://github.com/glitchwerks/claude-prospector/issues/63)
**Hook script:** `hooks/session-audit-prompt.py`

---

## Goal

The goal of this spike is to determine whether a Claude Code `Stop` hook can
reliably elicit a structured `<self-audit>` block from the main agent at the
end of a session turn. The block captures four sections: the original ask
(verbatim), what was done (file-level summary), what was skipped, and any
variance from the stated approach. If elicitation is reliable across a
representative range of session shapes, the hook can be wired into the plugin
manifest (`hooks/hooks.json`) and become part of the standard session-close
flow, feeding issue #63's session-summary and drift-detection machinery.

---

## How to register the hook locally for spike testing

This hook is **not** in `hooks/hooks.json` and will not activate for plugin
users. To test it locally, add a Stop hook entry to your **user-level** Claude
Code settings (`~/.claude/settings.json`). User-level settings are not shipped
with the plugin and affect only your local installation.

Locate (or create) `~/.claude/settings.json` and merge in the following
fragment, adjusting the path to match where this worktree lives on your
machine:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"I:\\other\\claude-prospector\\.worktrees\\self-audit-spike-129\\hooks\\session-audit-prompt.py\""
          }
        ]
      }
    ]
  }
}
```

> **Note:** If `~/.claude/settings.json` already has a `hooks.Stop` array,
> append the new entry to that array rather than replacing it. Hook arrays are
> processed in order; this hook can safely run alongside the plugin's
> `dashboard-regen.py` Stop hook.

> **Windows path escaping:** JSON requires backslashes to be doubled
> (`\\`). Adjust the path above if your repo is checked out elsewhere.

After saving, open a new Claude Code session. The hook fires automatically
when the session ends (i.e., when the user has no pending follow-up and the
agent is about to halt).

---

## Session shapes to exercise

Run at least one prompt per shape and record results in the table below.

### 1. Code fix

**Example prompt:**
> Fix the off-by-one error in `src/claude_prospector/paths.py` line 42.

**Expected self-audit content:**
- `### Original ask` — the verbatim fix request
- `### What was done` — `src/claude_prospector/paths.py` — fixed off-by-one
  in `<function name>`
- `### What was NOT done` — nothing skipped (single-file fix)
- `### Variance` — no variance (or: noted related issue in nearby code,
  did not fix)

### 2. Discussion-only / lookup turn

**Example prompt:**
> What does the `stop_hook_active` field do in a Stop hook payload?

**Expected self-audit content:**
- `### Original ask` — verbatim question
- `### What was done` — no code changes — discussion / lookup turn
- `### What was NOT done` — nothing skipped
- `### Variance` — no variance

### 3. Multi-step plan execution

**Example prompt:**
> Add a `--dry-run` flag to the `dashboard` subcommand: parse the arg,
> skip writing the output file, and print what would have been written to
> stdout instead.

**Expected self-audit content:**
- `### Original ask` — verbatim multi-step request
- `### What was done` — multiple file lines (CLI parser, dashboard writer,
  tests)
- `### What was NOT done` — items listed if any step was deferred; otherwise
  "nothing skipped"
- `### Variance` — any scope creep or approach pivot (e.g., "used
  `argparse` subparser instead of top-level flag as originally stated")

### 4. Mid-task abandonment / partial completion

**Example prompt:**
> Refactor the `_base_dir` function in `hooks/dashboard-regen.py` to use a
> dataclass, update all three callers, and add a unit test.

**Expected self-audit content (if the agent stops after touching only one
caller):**
- `### Original ask` — verbatim three-part request
- `### What was done` — `hooks/dashboard-regen.py` — refactored `_base_dir`
  to dataclass
- `### What was NOT done` — two callers not updated; unit test not written
- `### Variance` — no variance (or: discovered third caller in unexpected
  module)

### 5. Single-question lookup

**Example prompt:**
> What Python version is required by this project's `pyproject.toml`?

**Expected self-audit content:**
- `### Original ask` — verbatim lookup question
- `### What was done` — no code changes — discussion / lookup turn
- `### What was NOT done` — nothing skipped
- `### Variance` — no variance

---

## Parseability rubric

An emission counts as **clean** when all of the following are true:

1. **Wrapper tags present** — the text contains exactly one `<self-audit>`
   opening tag and exactly one `</self-audit>` closing tag (case-insensitive
   match; whitespace before/after tags is acceptable).

2. **All four section headers present, in order** — the block must contain
   all four of the following `###` headers in this sequence:
   - `### Original ask`
   - `### What was done`
   - `### What was NOT done`
   - `### Variance`
   Case-insensitive header matching is acceptable for scoring purposes, but
   exact case is preferred.

3. **No content outside the wrapper** — the assistant message that contains
   the self-audit block should not have substantive text before
   `<self-audit>` or after `</self-audit>`. A brief preamble line (e.g.,
   "Here is the self-audit:") is a minor deviation, not a failure.

4. **All four sections non-empty** — each section must contain at least one
   non-whitespace line of content (the defined placeholder strings such as
   "nothing skipped" count as non-empty).

---

## How to inspect a session transcript

Claude Code writes session transcripts as line-delimited JSON (JSONL) files at:

```
~/.claude/projects/<url-encoded-project-path>/<session-id>.jsonl
```

For example, a session on the prospector worktree might be at:

```
~/.claude/projects/I_other_claude-prospector_.worktrees_self-audit-spike-129/<session-id>.jsonl
```

### Extract the last assistant message

```bash
# Print all assistant message lines from the transcript
grep '"role":"assistant"' ~/.claude/projects/<project>/<session-id>.jsonl | tail -1
```

Or using Python (handles multi-line content blocks correctly):

```python
import json, sys

path = sys.argv[1]
last = None
with open(path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("role") == "assistant":
            last = ev
if last:
    content = last.get("content", "")
    if isinstance(content, list):
        text = "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        text = content
    print(text)
```

### Extract the `<self-audit>` block with regex

```python
import re, sys

text = sys.stdin.read()
m = re.search(r"<self-audit>(.*?)</self-audit>", text, re.IGNORECASE | re.DOTALL)
if m:
    print(m.group(0))
else:
    print("NO SELF-AUDIT BLOCK FOUND")
```

Pipe the Python extractor above into this regex extractor for a two-step
inspection:

```bash
python extract_last_assistant.py <transcript.jsonl> | python extract_audit.py
```

---

## Recording results

Fill in one row per test session:

| Session shape            | Emitted? | All 4 sections? | Clean (no outside text)? | Notes |
| ------------------------ | -------- | --------------- | ------------------------ | ----- |
| Code fix                 |          |                 |                          |       |
| Discussion / lookup      |          |                 |                          |       |
| Multi-step plan          |          |                 |                          |       |
| Mid-task abandonment     |          |                 |                          |       |
| Single-question lookup   |          |                 |                          |       |

Add additional rows for variant sessions as needed.

---

## Exit-option mapping

After running the spike, score the results against the rubric and map to one
of three outcomes:

### Reliable (≥ 4/5 shapes: emitted, all 4 sections, clean)

The hook elicitation strategy works. Proceed to:
- Wire `session-audit-prompt.py` into `hooks/hooks.json` (or a user-level
  settings block in the plugin manifest).
- Close #129 and update #63 with the confirmed approach.
- Design the downstream parser that reads `<self-audit>` blocks from
  transcripts for drift detection and session summaries.

### Partial (2–3/5 shapes meet the full rubric)

The block is emitted but reliability varies by session shape. Before
promoting to production:
- Identify which shapes fail and why (wrong section order, missing
  sections, narration outside the wrapper).
- Iterate on `_AUDIT_PROMPT` to close the gaps.
- Re-run the failing shapes with the revised prompt.
- Target reliable outcome before wiring into the manifest.

### Unreliable (≤ 1/5 shapes meet the full rubric)

The Stop hook block approach is not viable as written. Before closing #129
as "approach does not work":
- Check whether the transcript JSONL is being read correctly (use the
  inspection commands above to verify the hook is seeing the right message).
- Check whether `stop_hook_active` is prematurely bailing out on the first
  block (look for the bail-out stderr line).
- If the transcript-read is correct but the agent still doesn't emit the
  block, document the failure mode and raise a follow-up issue on #63
  exploring alternative elicitation strategies (e.g., injecting the audit
  request at `UserPromptSubmit` as a system note, or using a structured
  output tool call).
