# Self-Audit Stop Hook — Spike Methodology (Concluded — Cancelled)

> **Status: CANCELLED / concluded exploratory spike — retained as historical record only.**
>
> The elicitation hypothesis was validated (5/5 session shapes met the full rubric), but the Stop-hook mechanism was rejected on cost and UX grounds: issue [#161](https://github.com/glitchwerks/claude-prospector/issues/161) found it costs approximately 750 tokens per session and surfaces as a red error in the UI. The spike branch `self-audit-spike-129` was retired and its hook code (`hooks/session-audit-prompt.py`, install scripts) was discarded.
>
> Work pivoted to a transcript-based analyzer: issue [#162](https://github.com/glitchwerks/claude-prospector/issues/162) (deterministic session-audit extractor) supersedes this spike and will be built on a fresh branch off `main`; [#163](https://github.com/glitchwerks/claude-prospector/issues/163) adds an on-demand LLM variance layer on top. Do not treat any section below as live instructions.
>
> **Conclusion date: 2026-06-01.**

**Date:** 2026-05-19
**Issue:** [#129](https://github.com/glitchwerks/claude-prospector/issues/129)
**Parent:** [#63](https://github.com/glitchwerks/claude-prospector/issues/63)
**Hook script:** `hooks/session-audit-prompt.py` _(discarded — not carried to main)_

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

This branch wires `session-audit-prompt.py` into `hooks/hooks.json`, but the
spike branch is never merged to `main`. To get the hook active, install the
worktree as a **local marketplace** named `claude-prospector-spike` (declared
by `.claude-plugin/marketplace.json` on this branch), then install the plugin
from it. The released `glitchwerks` marketplace stays registered; the spike
copy of `claude-prospector` replaces the released copy for the duration of
the spike.

Use the helper script. PowerShell (preferred on Windows) and Bash flavors
are both shipped; pick whichever your shell is:

```powershell
# PowerShell, from the worktree root:
.\scripts\spike-install.ps1 install   # add marketplace, swap to spike copy
.\scripts\spike-install.ps1 status    # show marketplaces + active install
.\scripts\spike-install.ps1 restore   # remove marketplace, restore release copy
```

```bash
# Bash, from the worktree root:
./scripts/spike-install.sh install
./scripts/spike-install.sh status
./scripts/spike-install.sh restore
```

What `install` runs, in order:

1. `claude plugin marketplace add <worktree>` — registers
   `claude-prospector-spike` as a marketplace pointing at this worktree.
2. `claude plugin uninstall claude-prospector` — removes any current install
   (the release copy from `glitchwerks` if you had one).
3. `claude plugin install claude-prospector@claude-prospector-spike` —
   installs the spike copy, which carries the registered Stop hook.
4. `uv pip install --python <spike-venv-python> --force-reinstall -e <worktree>` —
   installs the `claude_prospector` Python package **editable from this
   worktree** into the spike plugin's venv. This bypasses the `/setup-prospector`
   skill's default PyPI install path, which would otherwise pull a released
   wheel that does not contain the spike's experimental code. (Spikes are
   never published to PyPI; the worktree IS the source of truth.) Step 4 is
   skipped with a warning if the spike plugin venv has not been created yet
   — run `/setup-prospector` in a Claude Code session, then re-run
   `spike-install install` to pick it up. See issues #145, #146, #147 for the
   bug this step prevents.

What `restore` runs, in order:

1. `claude plugin uninstall claude-prospector` — removes the spike copy.
2. `claude plugin marketplace remove claude-prospector-spike` — drops the
   local marketplace registration.
3. `claude plugin install claude-prospector@glitchwerks` — reinstalls the
   released copy.

After `install`, open a new Claude Code session. The hook fires automatically
when the session ends — no user-level `~/.claude/settings.json` edit is
required, and the wiring survives `git stash` / `git clean` on the worktree
because the install record lives in `~/.claude/plugins/`, not in any file
under the repo.

> **Why this replaces the prior recipe:** the original spike doc instructed
> editing `~/.claude/settings.json` with an absolute path into the worktree.
> That setup was fragile — the settings entry was outside the repo and got
> lost when the worktree's state changed (the hook entry was pulled into a
> stash on 2026-05-22 and the elicitation stopped firing with no signal). The
> local-marketplace install is first-class: `claude plugin list` shows it,
> `claude plugin uninstall` cleans it up, no manual JSON editing required.

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
| Code fix                 | Yes      | Yes             | Yes                      | Session `83ad17d2` — clean |
| Discussion / lookup      | Yes      | Yes             | Yes                      | Session `19e31666` — clean |
| Multi-step plan          | Yes      | Yes             | Yes                      | Session `696584a5` — clean per rubric; see caveat in Conclusion |
| Mid-task abandonment     | Yes      | Yes             | Yes                      | Session `53a20603` — clean |
| Single-question lookup   | Yes      | Yes             | Yes                      | Session `eb48d9d8` — clean |

Add additional rows for variant sessions as needed.

---

## Conclusion

**Result: 5/5 shapes meet the full rubric → Reliable.**

Each of the five session shapes from `## Session shapes to exercise` was run as a deliberate test on 2026-05-25 in fresh sessions on the `self-audit-spike-129` branch with the spike plugin active. All five sessions emitted a single `<self-audit>` block on the agent's forced second turn, with all four headers in order, all four sections non-empty (no placeholder echoes), and no substantive content outside the wrapper.

### Caveat — Multi-step plan session (`696584a5`)

The multi-step plan session ran several distinct user turns after the initial "Add a `--dry-run` flag…" prompt (continuing through implementation, review, and PR-close steps). The agent's `### Original ask` section quoted the *last* user message ("close the pr") rather than the first user message of the session, despite the audit-prompt template's instruction (L72: "Verbatim quote of the first user message in this session").

This is a real prompt-vs-behavior gap but does not fail the rubric as written — criterion 4 only requires sections to be non-empty. It is worth tracking as a follow-up against #63 (the parent issue) so the downstream drift analyzer can be told whether to trust `Original ask` for long multi-task sessions, or alternatively have the hook itself inject the captured first-user-message text verbatim instead of asking the agent to recall it.

### What the spike recommended at the time (now superseded by #162)

Per `## Exit-option mapping` § Reliable (below), the spike's deliverable was met. At the time of the conclusion the recommended follow-up actions were:

1. Wire `session-audit-prompt.py` into the released plugin's `hooks/hooks.json` (the spike branch wired it locally; the released branch did not).
2. Close #129 and update parent #63 with the confirmed approach and the multi-step caveat above.
3. Design the downstream parser that reads `<self-audit>` blocks from transcripts for drift detection.

**None of these actions were taken via this branch.** Issue #161 identified that the Stop-hook mechanism incurred ~750 tokens per session and surfaced as a red error, making step 1 impractical. The pivot to #162 replaced all three steps: #162 implements a deterministic transcript-based extractor that does not require a Stop hook at all. The multi-step caveat (recall gap in `### Original ask`) is a real finding that #162 should account for — the extractor can inject the first-user-message verbatim rather than asking the agent to recall it.

---

## Exit-option mapping (spike design reference — not live instructions)

This section was the spike's decision framework, written before results were available. The "Reliable" branch was reached (5/5); however, the Stop-hook mechanism was subsequently rejected on cost/UX grounds (#161) before any production wiring occurred. The three branches are preserved here as historical context for how the spike was designed.

### Reliable (≥ 4/5 shapes: emitted, all 4 sections, clean)

_This branch was reached. The recommended actions listed here were not taken — see "What the spike recommended at the time" above._

The hook elicitation strategy was found to work. The planned next steps had been:
- Wire `session-audit-prompt.py` into `hooks/hooks.json` (or a user-level
  settings block in the plugin manifest).
- Close #129 and update #63 with the confirmed approach.
- Design the downstream parser that reads `<self-audit>` blocks from
  transcripts for drift detection and session summaries.

### Partial (2–3/5 shapes meet the full rubric)

_This branch was not reached._

The block is emitted but reliability varies by session shape. Before
promoting to production:
- Identify which shapes fail and why (wrong section order, missing
  sections, narration outside the wrapper).
- Iterate on `_AUDIT_PROMPT` to close the gaps.
- Re-run the failing shapes with the revised prompt.
- Target reliable outcome before wiring into the manifest.

### Unreliable (≤ 1/5 shapes meet the full rubric)

_This branch was not reached._

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
