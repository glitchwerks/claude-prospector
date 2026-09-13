# Session Effort Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, hash-routed per-session dashboard that reconciles token usage across recorded effort, model, agent, time, skills, commands, and opt-in MCP activity.

**Architecture:** Extend the existing parser and `agent_activity` payload with exact response facts, retain timestamped per-session MCP records only when the existing opt-in runs, and perform all chart bucketing and filtering client-side. A small hash router loads a focused `session-detail.js` view inside the current self-contained HTML artifact; pure JavaScript helpers own bucketing, scoping, tree selection, and ledger ordering so those behaviors can be executed under Node tests.

**Tech Stack:** Python 3.10+ (`pyproject.toml:L9`), frozen dataclasses, pytest, vanilla JavaScript, SVG, Node 22's built-in test runner, Jinja2, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-13-session-effort-analytics-design.md`

## Global Constraints

- Implement only deterministic transcript facts; never retain or infer prompts, thinking, intent, quality, actions, command arguments, tool inputs, or tool-result content (spec §§1, 3, 6, 13; #310).
- Preserve message-ID token deduplication and deduplicate Skill/MCP calls independently by tool-use identity (spec §§2-3, 10; `src/claude_prospector/parser.py:L420-L429`; `src/claude_prospector/tool_collection.py:L169-L178`).
- Keep every existing aggregate/session key and MCP opt-in default backward-compatible; all new payload fields are additive (spec §3.6; `src/claude_prospector/cli/dashboard.py:L139-L163`).
- Treat absent MCP collection as `Not collected`, successful empty collection as zero, and unreadable requested collection as unavailable (spec §§3.5, 9; #310).
- The whole-session overview keeps its full time domain; `All` ignores the brush for detail analytics and `By time period` applies the brush (spec §§5.2-5.4; #310).
- Agent filters start fully active and use recursive checked/unchecked/indeterminate subtree semantics over exact full paths (spec §5.5; #310).
- Full detail remains available without top-N truncation even when charts use adaptive buckets (spec §§5.1-5.3; #310).
- Keep the report one self-contained offline HTML file; no local server and no per-session files (spec §§4, 7, 12; `src/claude_prospector/renderer.py:L81-L129`).
- Use `CP.esc()` or DOM text nodes for every transcript-derived string rendered by new or modified client code (`src/claude_prospector/static/cp-utils.js:L69-L74`; spec §7).
- Run Python through `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on POSIX. Use `uv` for dependency changes (repository `AGENTS.md`, Python section).
- Use TDD for every behavior change and commit after every completed task (repository `AGENTS.md`, Testing and Git Commits sections).

---

## File responsibility map

| File | Responsibility in this feature |
|---|---|
| `src/claude_prospector/models.py` | Typed effort, Skill invocation, metadata observation, and tool timestamp records |
| `src/claude_prospector/parser.py` | Privacy-safe extraction, response deduplication, Skill deduplication, and metadata observations |
| `src/claude_prospector/aggregator.py` | Additive exact session payload, fact projection, reconciliation, and per-session MCP attachment |
| `src/claude_prospector/tool_collection.py` | Nullable tool-call timestamps without changing result-content privacy gates |
| `src/claude_prospector/cli/dashboard.py` | Attach successful/unavailable MCP collection states to in-window sessions |
| `src/claude_prospector/static/cp-utils.js` | Pure bucketing, scope, totals, tree selection, and ledger helpers |
| `src/claude_prospector/static/views/session-detail.js` | Session page DOM, SVG charts, controls, expanded details, and cleanup |
| `src/claude_prospector/static/views/economics-basic.js` | Clickable recent-session links from Overview |
| `src/claude_prospector/static/views/layout-b-diag.js` | Clickable recent-session links plus return-state handoff from Breakdown |
| `src/claude_prospector/templates/dashboard.html` | Hash router and session-view lifecycle |
| `src/claude_prospector/renderer.py` | Inline the new view resource |
| `tests/fixtures/session-analytics/*.json` | Short, long/concurrent, and deep nested deterministic client fixtures |
| `tests/js/session-analytics.test.js` | Executable pure-client behavior contract |
| `.github/workflows/ci.yml` | Pinned Node setup and client tests inside the existing test check |
| `README.md` | User behavior, privacy semantics, and contributor test command |

The map follows the existing split between parser, aggregator, static view files,
renderer, and packaged template (`src/claude_prospector/parser.py:L478-L567`;
`src/claude_prospector/aggregator.py:L160-L345`;
`src/claude_prospector/renderer.py:L116-L129`).

## Spec-to-task coverage

| Approved spec requirement | Implementing tasks |
|---|---|
| Exact effort and response facts (§§3.1, 10) | 1, 2 |
| Complete actual Skills, commands, and session facts (§§3.2-3.4) | 1, 2, 8 |
| MCP opt-in/null/zero/unavailable semantics (§§3.5, 9) | 3, 8 |
| Additive payload compatibility (§3.6) | 2, 3, 9 |
| Hash route, Back, and not-found state (§4) | 5, 9 |
| Scan-first full expansion with no truncation (§5.1) | 6, 8 |
| Adaptive whole-session overview and exact scoped bars (§§5.2-5.4) | 4, 7 |
| Recursive tri-state subagent filtering and concurrent tracks (§§5.5-5.6) | 4, 6, 7 |
| Deterministic chronological ledger (§6) | 4, 8 |
| Offline client architecture and escaping (§7) | 4-8 |
| Accessibility, responsive behavior, and missing states (§§8-9) | 5-9 |
| Automated/manual verification and README rollout (§§11-12) | 1-9 |

Every row maps directly to the approved design spec and #310; no interpretive
session-analysis behavior is introduced.

---

### Task 1: Parse effort, complete Skill invocations, and session metadata

**Files:**
- Modify: `src/claude_prospector/models.py:9-184`
- Modify: `src/claude_prospector/parser.py:313-567`
- Modify: `tests/test_models.py`
- Modify: `tests/test_parser.py`
- Use fixture: `tests/fixtures/duplicate_message_id.jsonl`

**Interfaces:**
- Consumes: transcript entries and `AgentTranscript.agent_path` from the existing walker.
- Produces: `MessageRecord.effort`, `SkillInvocationRecord`, `SessionMetadataObservation`, `SessionRecord.skill_invocations`, `SessionRecord.metadata_observations`, `SessionRecord.agent_paths`, and `SessionRecord.effort_conflicts` for Task 2.

- [ ] **Step 1: Add failing model and parser tests**

Add dataclass assertions in `tests/test_models.py` and parser cases in
`tests/test_parser.py`. Build JSONL with `tmp_path.write_text()` and verify that
the parser never retains Skill arguments or surrounding message text:

```python
_USAGE = {
    "input_tokens": 1,
    "output_tokens": 2,
    "cache_read_input_tokens": 3,
    "cache_creation_input_tokens": 4,
}


def _assistant_entry(
    message_id: str,
    effort: object,
    *,
    timestamp: str,
    content: list[dict] | None = None,
    uuid: str | None = None,
    git_branch: str | None = None,
    entrypoint: str | None = None,
    version: str | None = None,
) -> dict:
    entry = {
        "type": "assistant",
        "uuid": uuid or f"entry-{message_id}-{timestamp}",
        "timestamp": timestamp,
        "effort": effort,
        "message": {
            "id": message_id,
            "model": "claude-sonnet-5",
            "content": content or [{"type": "text", "text": "excluded"}],
            "usage": dict(_USAGE),
        },
    }
    if git_branch is not None:
        entry["gitBranch"] = git_branch
    if entrypoint is not None:
        entry["entrypoint"] = entrypoint
    if version is not None:
        entry["version"] = version
    return entry


def _write_session(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return path


def _write_skill_fragment_session(tmp_path: Path) -> Path:
    first = _assistant_entry(
        "msg-skill",
        "high",
        timestamp="2026-09-13T10:00:00Z",
        content=[{
            "type": "tool_use",
            "id": "tool-python",
            "name": "Skill",
            "input": {"skill": "python", "args": "secret args"},
        }],
    )
    duplicate = _assistant_entry(
        "msg-skill",
        "high",
        timestamp="2026-09-13T10:00:01Z",
        content=[{
            "type": "tool_use",
            "id": "tool-python",
            "name": "Skill",
            "input": {"skill": "python", "args": "secret args"},
        }],
    )
    second = _assistant_entry(
        "msg-skill",
        "high",
        timestamp="2026-09-13T10:00:02Z",
        content=[{
            "type": "tool_use",
            "id": "tool-frontend",
            "name": "Skill",
            "input": {"skill": "frontend-design"},
        }],
    )
    return _write_session(tmp_path, [first, duplicate, second])


def _write_metadata_session(tmp_path: Path) -> Path:
    return _write_session(
        tmp_path,
        [
            _assistant_entry(
                "msg-1",
                "high",
                timestamp="2026-09-13T10:00:00Z",
                git_branch="main",
                entrypoint="cli",
                version="2.1.220",
            ),
            _assistant_entry(
                "msg-2",
                "high",
                timestamp="2026-09-13T10:01:00Z",
                git_branch="codex/session-effort-analytics",
            ),
        ],
    )


def test_effort_is_trimmed_and_future_values_are_preserved(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _assistant_entry("msg-1", " high ", timestamp="2026-09-13T10:00:00Z"),
            _assistant_entry("msg-2", "xhigh", timestamp="2026-09-13T10:01:00Z"),
            _assistant_entry("msg-3", 42, timestamp="2026-09-13T10:02:00Z"),
            _assistant_entry("msg-4", "   ", timestamp="2026-09-13T10:03:00Z"),
        ],
    )
    session = _parse_session(path, "project")
    assert session is not None
    assert [message.effort for message in session.messages] == [
        "high",
        "xhigh",
        None,
        None,
    ]


def test_duplicate_fragments_fill_missing_effort_and_count_conflicts(
    tmp_path: Path,
) -> None:
    path = _write_session(
        tmp_path,
        [
            _assistant_entry("msg-1", None, timestamp="2026-09-13T10:00:00Z"),
            _assistant_entry("msg-1", "high", timestamp="2026-09-13T10:00:01Z"),
            _assistant_entry("msg-1", "low", timestamp="2026-09-13T10:00:02Z"),
        ],
    )
    session = _parse_session(path, "project")
    assert session is not None
    assert len(session.messages) == 1
    assert session.messages[0].effort == "high"
    assert session.effort_conflicts == 1


def test_skill_blocks_are_complete_and_deduplicated_by_tool_use_id(
    tmp_path: Path,
) -> None:
    path = _write_skill_fragment_session(tmp_path)
    session = _parse_session(path, "project")
    assert session is not None
    assert [event.skill for event in session.skill_invocations] == ["python", "frontend-design"]
    assert all(event.agent_path == ("main",) for event in session.skill_invocations)
    assert "secret args" not in repr(session.skill_invocations)


def test_skill_blocks_without_tool_message_or_entry_ids_use_entry_ordinal(
    tmp_path: Path,
) -> None:
    entries = [
        _assistant_entry(
            "",
            "high",
            uuid="",
            timestamp=f"2026-09-13T10:00:0{second}Z",
            content=[{
                "type": "tool_use",
                "name": "Skill",
                "input": {"skill": "python"},
            }],
        )
        for second in (0, 1)
    ]
    for entry in entries:
        entry.pop("uuid", None)
        entry["message"].pop("id", None)
    session = _parse_session(_write_session(tmp_path, entries), "project")
    assert session is not None
    assert [event.skill for event in session.skill_invocations] == ["python", "python"]


def test_subagent_skill_invocation_retains_full_path(tmp_path: Path) -> None:
    root = _write_session(
        tmp_path,
        [_assistant_entry("root", "high", timestamp="2026-09-13T10:00:00Z")],
    )
    child_dir = tmp_path / root.stem / "subagents"
    child_dir.mkdir(parents=True)
    (child_dir / "agent-child.meta.json").write_text(
        json.dumps({"agentType": "worker"}),
        encoding="utf-8",
    )
    child_entry = _assistant_entry(
        "child",
        "low",
        timestamp="2026-09-13T10:00:01Z",
        content=[{
            "type": "tool_use",
            "id": "child-skill",
            "name": "Skill",
            "input": {"skill": "python"},
        }],
    )
    (child_dir / "agent-child.jsonl").write_text(
        json.dumps(child_entry),
        encoding="utf-8",
    )
    session = _parse_session(root, "project")
    assert session is not None
    assert session.skill_invocations[0].agent_path == ("general-purpose", "worker")


def test_metadata_observations_retain_distinct_recorded_values(tmp_path: Path) -> None:
    path = _write_metadata_session(tmp_path)
    session = _parse_session(path, "project")
    assert session is not None
    assert {(item.name, item.value) for item in session.metadata_observations} == {
        ("git_branch", "main"),
        ("git_branch", "codex/session-effort-analytics"),
        ("entrypoint", "cli"),
        ("claude_code_version", "2.1.220"),
    }
```

- [ ] **Step 2: Run the focused tests and confirm the red state**

Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_models.py tests/test_parser.py -q
```

Expected: failures for missing fields/classes and incomplete Skill extraction.

- [ ] **Step 3: Add the typed records and additive SessionRecord fields**

Add the following shapes to `models.py`, keeping defaults after existing
required fields so current keyword constructors remain valid:

```python
@dataclass(frozen=True, slots=True)
class SkillInvocationRecord:
    skill: str
    timestamp: datetime
    agent_path: tuple[str, ...]
    tool_use_id: str = ""


@dataclass(frozen=True, slots=True)
class SessionMetadataObservation:
    name: str
    value: str
    timestamp: datetime
    agent_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MessageRecord:
    # Existing fields stay in their current order.
    agent_path: tuple[str, ...] = ()
    effort: str | None = None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    # Existing fields stay unchanged.
    commands: list[CommandInvocationRecord] = field(default_factory=list)
    skill_invocations: list[SkillInvocationRecord] = field(default_factory=list)
    metadata_observations: list[SessionMetadataObservation] = field(default_factory=list)
    agent_paths: list[tuple[str, ...]] = field(default_factory=list)
    effort_conflicts: int = 0
```

Update the docstrings with the privacy and deduplication semantics from spec
§3. `SkillInvokedEvent` remains unchanged because it represents hook-log
adoption data, not transcript session activity
(`src/claude_prospector/models.py:L132-L149`).

- [ ] **Step 4: Implement extraction before response deduplication**

In `parser.py`, replace `_extract_skill()` with helpers that return every valid
Skill block while preserving the first Skill for `MessageRecord.skill`:

```python
_SESSION_METADATA_FIELDS = {
    "gitBranch": "git_branch",
    "entrypoint": "entrypoint",
    "version": "claude_code_version",
}


def _parse_effort(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _extract_skill_invocations(
    content: list[dict],
    *,
    timestamp: datetime,
    agent_path: tuple[str, ...],
    message_id: str | None,
    entry_id: str | None,
    entry_ordinal: int,
    transcript_key: str,
) -> list[tuple[tuple[object, ...], SkillInvocationRecord]]:
    found = []
    for index, block in enumerate(content):
        if block.get("type") != "tool_use" or block.get("name") != "Skill":
            continue
        payload = block.get("input")
        skill = payload.get("skill") if isinstance(payload, dict) else None
        if not isinstance(skill, str) or not skill.strip():
            continue
        tool_use_id = block.get("id") if isinstance(block.get("id"), str) else ""
        identity = (
            ("tool", transcript_key, tool_use_id)
            if tool_use_id
            else (
                "fallback",
                transcript_key,
                message_id or entry_id or entry_ordinal,
                index,
                skill.strip(),
            )
        )
        found.append(
            (
                identity,
                SkillInvocationRecord(
                    skill=skill.strip(),
                    timestamp=timestamp,
                    agent_path=agent_path,
                    tool_use_id=tool_use_id,
                ),
            )
        )
    return found
```

Within `_parse_jsonl_records()`, enumerate input lines so `entry_ordinal` is
stable within the transcript unit, parse each entry timestamp once when present,
append new Skill identities before the duplicate-message early return, collect
only the three allowlisted metadata fields, and merge effort deterministically:

```python
candidate_effort = _parse_effort(entry.get("effort"))
if message_id is not None and message_id in message_indexes:
    index = message_indexes[message_id]
    existing = messages[index]
    if existing.effort is None and candidate_effort is not None:
        messages[index] = replace(existing, effort=candidate_effort)
    elif (
        existing.effort is not None
        and candidate_effort is not None
        and existing.effort != candidate_effort
    ):
        effort_conflicts += 1
    continue
```

Return the new collections from `_parse_jsonl_records()`, adapt
`_parse_jsonl_messages()`, and merge each transcript unit's results in
`_parse_session()`. Set `agent_paths=[unit.agent_path for unit in transcripts]`
so discovered root/child transcripts remain visible even when one produced no
assistant response. Do not parse prompt or result content. This extends the
existing single-pass parser and recursive walker integration
(`src/claude_prospector/parser.py:L361-L448`,
`src/claude_prospector/parser.py:L538-L567`).

- [ ] **Step 5: Run focused parser/model tests and the existing parser regression suite**

Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_models.py tests/test_parser.py tests/test_transcript_walker.py -q
```

Expected: all selected tests pass, including the committed duplicate-message
fixture.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/claude_prospector/models.py src/claude_prospector/parser.py tests/test_models.py tests/test_parser.py
git commit -m "feat: capture session effort and activity facts (#310)"
```

---

### Task 2: Emit the exact additive session payload and reconciliation facts

**Files:**
- Modify: `src/claude_prospector/aggregator.py:66-345`
- Modify: `tests/test_aggregator.py`
- Create: `tests/test_session_detail_payload.py`

**Interfaces:**
- Consumes: the Task 1 `MessageRecord`, `SkillInvocationRecord`, and `SessionMetadataObservation` fields.
- Produces: additive `agent_activity`, `skill_activity`, `command_activity`, `session_facts`, `end_time`, `duration_seconds`, `agent_paths`, `mcp_collection`, and `mcp_activity` keys consumed by Tasks 3, 4, and 6.

- [ ] **Step 1: Write failing exact-payload and reconciliation tests**

Add a multi-message, multi-agent `SessionRecord` fixture and assert the full
response contract, `Unknown` key, facts, complete Skills, root-attributed
commands, and all rollup invariants:

```python
def test_session_detail_payload_is_exact_and_additive() -> None:
    result = aggregate([_effort_session()])
    session = result.sessions[0]
    assert session["agent_activity"][0] == {
        "timestamp": "2026-09-13T10:00:00+00:00",
        "agent": "main",
        "agent_path": ["main"],
        "model": "sonnet",
        "model_full": "claude-sonnet-5",
        "effort": "high",
        "effort_key": "high",
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_tokens": 30,
        "cache_creation_tokens": 40,
        "total_tokens": 100,
    }
    assert session["mcp_collection"] == {
        "calls": "not_collected",
        "result_sizes": "not_collected",
    }
    assert session["mcp_activity"] is None


def test_response_dimensions_reconcile_to_session_total() -> None:
    session = aggregate([_effort_session()]).sessions[0]
    responses = session["agent_activity"]
    assert sum(row["total_tokens"] for row in responses) == session["total_tokens"]
    assert sum(row["input_tokens"] for row in responses) == session["input_tokens"]
    assert sum(row["output_tokens"] for row in responses) == session["output_tokens"]
    assert sum(row["cache_read_tokens"] for row in responses) == session["cache_read_tokens"]
    assert sum(row["cache_creation_tokens"] for row in responses) == session["cache_creation_tokens"]
    assert sum(session["effort_split"].values()) == session["total_tokens"]
```

Define `_effort_session()` in `tests/test_session_detail_payload.py` with this
exact deterministic data, importing the Task 1 record classes:

```python
def _effort_session() -> SessionRecord:
    start = datetime(2026, 9, 13, 10, tzinfo=timezone.utc)
    messages = [
        MessageRecord(
            timestamp=start,
            model="claude-sonnet-5",
            agent_type="main",
            skill="python",
            input_tokens=10,
            output_tokens=20,
            cache_read_tokens=30,
            cache_creation_tokens=40,
            agent_path=("main",),
            effort="high",
        ),
        MessageRecord(
            timestamp=start + timedelta(minutes=1),
            model="claude-opus-5",
            agent_type="worker",
            skill=None,
            input_tokens=1,
            output_tokens=2,
            cache_read_tokens=3,
            cache_creation_tokens=4,
            agent_path=("main", "worker"),
            effort=None,
        ),
    ]
    return SessionRecord(
        session_id="effort-session",
        project="project",
        project_path="/project",
        start_time=start,
        root_agent="main",
        messages=messages,
        subagent_types=["worker"],
        agent_paths=[("main",), ("main", "worker")],
        commands=[CommandInvocationRecord(name="/compact", timestamp=start)],
        skill_invocations=[
            SkillInvocationRecord(
                skill="python",
                timestamp=start,
                agent_path=("main",),
                tool_use_id="tool-python",
            )
        ],
        metadata_observations=[
            SessionMetadataObservation(
                name="git_branch",
                value="main",
                timestamp=start,
                agent_path=("main",),
            )
        ],
    )
```

Also test CLI-window filtering for response, Skill, and Command timestamps, and
prove existing `agent_tokens`, `agent_stats`, `model_split`, and
`duration_minutes` keys remain present. This protects the current session
summary contract (`src/claude_prospector/aggregator.py:L220-L276`).

- [ ] **Step 2: Run the new payload tests and confirm the red state**

Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_aggregator.py tests/test_session_detail_payload.py -q
```

Expected: failures for the additive fields and complete activity lists.

- [ ] **Step 3: Extend `_agent_activity()` and add projection helpers**

Implement exact effort grouping without restricting future labels:

```python
def _effort_key(effort: str | None) -> str:
    return effort.casefold() if effort else "unknown"


def _agent_activity(msg: MessageRecord) -> dict:
    return {
        "timestamp": msg.timestamp.isoformat(),
        "agent": _path_key(msg),
        "agent_path": list(msg.agent_path),
        "model": msg.model_short,
        "model_full": msg.model,
        "effort": msg.effort,
        "effort_key": _effort_key(msg.effort),
        "input_tokens": msg.input_tokens,
        "output_tokens": msg.output_tokens,
        "total_tokens": msg.total_tokens,
        "cache_creation_tokens": msg.cache_creation_tokens,
        "cache_read_tokens": msg.cache_read_tokens,
    }
```

Add `_in_window(timestamp, from_date, to_date)`, `_skill_activity()`,
`_command_activity()`, and `_session_fact_values()`. The fact helper groups
metadata by `(name, value)`, selects `min(timestamp)` as `first_seen`, and emits
sorted unique agent paths; it never chooses a preferred branch/version.

```python
def _skill_activity(event: SkillInvocationRecord) -> dict:
    return {
        "timestamp": event.timestamp.isoformat(),
        "agent": AGENT_PATH_SEPARATOR.join(event.agent_path),
        "agent_path": list(event.agent_path),
        "skill": event.skill,
    }


def _command_activity(
    event: CommandInvocationRecord,
    agent_path: tuple[str, ...],
) -> dict:
    return {
        "timestamp": event.timestamp.isoformat(),
        "agent": AGENT_PATH_SEPARATOR.join(agent_path),
        "agent_path": list(agent_path),
        "name": event.name,
    }


def _session_fact_values(
    observations: list[SessionMetadataObservation],
) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for observation in observations:
        key = (observation.name, observation.value)
        row = grouped.setdefault(
            key,
            {
                "name": observation.name,
                "value": observation.value,
                "first_seen": observation.timestamp,
                "agent_paths": set(),
            },
        )
        row["first_seen"] = min(row["first_seen"], observation.timestamp)
        row["agent_paths"].add(observation.agent_path)
    return [
        {
            **row,
            "first_seen": row["first_seen"].isoformat(),
            "agent_paths": [list(path) for path in sorted(row["agent_paths"])],
        }
        for row in sorted(
            grouped.values(),
            key=lambda item: (item["first_seen"], item["name"], item["value"]),
        )
    ]
```

- [ ] **Step 4: Populate additive fields inside the existing session summary**

Build `effort_split` from `session_messages` and add:

```python
activity_start = min(message.timestamp for message in session_messages)
activity_end = max(message.timestamp for message in session_messages)
effort_tokens: dict[str, int] = defaultdict(int)
for message in session_messages:
    effort_tokens[_effort_key(message.effort)] += message.total_tokens
session_skill_events = [
    event
    for event in session.skill_invocations
    if _in_window(event.timestamp, from_date, to_date)
]
session_command_events = [
    event for event in session.commands if _in_window(event.timestamp, from_date, to_date)
]

summary.update(
    {
        "end_time": activity_end.isoformat(),
        "duration_seconds": int((activity_end - activity_start).total_seconds()),
        "agent_paths": [list(path) for path in sorted(set(session.agent_paths))],
        "effort_split": dict(effort_tokens),
        "skill_activity": [_skill_activity(event) for event in session_skill_events],
        "command_activity": [
            _command_activity(event, (session.root_agent,))
            for event in session_command_events
        ],
        "session_facts": {
            "metadata": _session_fact_values(session.metadata_observations),
            "effort_conflicts": session.effort_conflicts,
        },
        "mcp_collection": {
            "calls": "not_collected",
            "result_sizes": "not_collected",
        },
        "mcp_activity": None,
    }
)
```

Sort every activity array by `(timestamp, original ordinal)` and keep the
existing filtered message totals untouched. This makes the new dimensions
reconcile with the applicable session summary rather than a second total
(spec §10; `src/claude_prospector/aggregator.py:L185-L201`).

- [ ] **Step 5: Run payload, aggregation, CLI JSON, and renderer tests**

Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_aggregator.py tests/test_session_detail_payload.py tests/test_cli.py tests/test_renderer.py -q
```

Expected: all selected tests pass and legacy JSON keys remain unchanged.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/claude_prospector/aggregator.py tests/test_aggregator.py tests/test_session_detail_payload.py
git commit -m "feat: emit exact session analytics payload (#310)"
```

---

### Task 3: Retain timestamped per-session MCP activity behind existing opt-ins

**Files:**
- Modify: `src/claude_prospector/models.py:151-184`
- Modify: `src/claude_prospector/tool_collection.py:157-281`
- Modify: `src/claude_prospector/aggregator.py:435-606`
- Modify: `src/claude_prospector/cli/dashboard.py:218-243`
- Modify: `tests/unit/test_tool_collection.py`
- Modify: `tests/test_aggregator_tool_usage.py`
- Modify: `tests/test_dashboard_mcp_usage.py`
- Modify: `tests/test_dashboard_mcp_call_sizes.py`

**Interfaces:**
- Consumes: Task 2's default `mcp_collection` and `mcp_activity` session keys plus existing `collect_per_session()` output.
- Produces: `ToolUseRecord.timestamp: datetime | None` and `attach_session_mcp_activity(result, per_session, *, track_mcp_call_sizes)` for `cli/dashboard.py`.

- [ ] **Step 1: Add failing collection-state and timestamp tests**

Cover recorded timestamp, missing/malformed timestamp without call loss,
successful zero calls, successful calls, unreadable transcript, and independent
result-size state:

```python
def test_collect_unit_adds_timestamp_without_reading_result_content(tmp_path: Path) -> None:
    path = tmp_path / "agent.jsonl"
    _write_jsonl(
        path,
        [
            _tool_use_line(
                "session",
                "message",
                "tool-call",
                "mcp__github__get_issue",
                "entry",
                "2026-09-13T11:00:00Z",
            )
        ],
    )
    unit = AgentTranscript(path, "main", ("main",))
    records, _ = collect_unit(unit, track_mcp_call_sizes=False)
    assert records[0].timestamp == datetime(2026, 9, 13, 11, tzinfo=timezone.utc)
    assert records[0].result_chars is None


def test_attach_session_mcp_activity_distinguishes_all_collection_states() -> None:
    result = AggregateResult(
        sessions=[_session_summary("ok"), _session_summary("empty"), _session_summary("missing")]
    )
    attach_session_mcp_activity(
        result,
        [
            ("ok", [_mcp_record("mcp__github__get_issue")], []),
            ("empty", [], []),
        ],
        track_mcp_call_sizes=False,
    )
    assert result.sessions[0]["mcp_collection"]["calls"] == "collected"
    assert result.sessions[0]["mcp_activity"][0]["server"] == "github"
    assert result.sessions[1]["mcp_activity"] == []
    assert result.sessions[2]["mcp_collection"]["calls"] == "unavailable"
    assert result.sessions[2]["mcp_collection"]["warning"] == "transcript_unavailable"
```

Define the two Task 3 aggregation helpers in the test module:

```python
def _session_summary(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "mcp_collection": {
            "calls": "not_collected",
            "result_sizes": "not_collected",
        },
        "mcp_activity": None,
    }


def _mcp_record(tool_name: str) -> ToolUseRecord:
    return ToolUseRecord(
        tool_name=tool_name,
        tool_use_id="tool-call",
        agent_type="main",
        agent_path=("main",),
        timestamp=datetime(2026, 9, 13, 11, tzinfo=timezone.utc),
    )
```

Assert that built-in tools and malformed MCP names do not enter
`mcp_activity`, while existing global malformed-name warnings remain accurate.

- [ ] **Step 2: Run MCP-focused tests and confirm the red state**

Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_tool_collection.py tests/test_aggregator_tool_usage.py tests/test_dashboard_mcp_usage.py tests/test_dashboard_mcp_call_sizes.py -q
```

Expected: failures for `timestamp` and `attach_session_mcp_activity`.

- [ ] **Step 3: Add nullable timestamps without weakening collection**

Add `timestamp: datetime | None = None` to `ToolUseRecord`. In
`tool_collection.py`, parse assistant-entry timestamps with a local helper that
returns `None` on missing, non-string, or invalid input:

```python
def _optional_timestamp(entry: dict) -> datetime | None:
    raw = entry.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
```

Pass this value to every `ToolUseRecord`. Do not skip a call solely because its
timestamp is unavailable, and do not enter the `tool_result` branch unless
`track_mcp_call_sizes` is true. The existing privacy gate is explicit at
`src/claude_prospector/tool_collection.py:L188-L203`.

- [ ] **Step 4: Implement per-session MCP attachment**

Add this public aggregator helper beside `compute_tool_usage()`:

```python
def attach_session_mcp_activity(
    result: AggregateResult,
    per_session: list[tuple[str, list[ToolUseRecord], list[AgentAvailability]]],
    *,
    track_mcp_call_sizes: bool,
) -> None:
    collected = {session_id: records for session_id, records, _ in per_session}
    for summary in result.sessions:
        records = collected.get(summary["session_id"])
        if records is None:
            summary["mcp_collection"] = {
                "calls": "unavailable",
                "result_sizes": "unavailable" if track_mcp_call_sizes else "not_collected",
                "warning": "transcript_unavailable",
            }
            summary["mcp_activity"] = None
            continue
        summary["mcp_collection"] = {
            "calls": "collected",
            "result_sizes": "collected" if track_mcp_call_sizes else "not_collected",
        }
        summary["mcp_activity"] = _session_mcp_records(records)
```

`_session_mcp_records()` calls `normalize_mcp_tool_name()`, splits its
`server.method` result once, emits exact agent path/timestamp/result-size
fields, and sorts null timestamps after recorded timestamps. It emits one row
per deduplicated call with `call_count: 1`; it never includes raw names,
arguments, or result content (spec §3.5;
`src/claude_prospector/mcp_names.py:L6-L38`).

```python
def _session_mcp_records(records: list[ToolUseRecord]) -> list[dict]:
    activity = []
    for record in records:
        normalized = normalize_mcp_tool_name(record.tool_name)
        if normalized is None:
            continue
        server, _, method = normalized.partition(".")
        activity.append(
            {
                "timestamp": record.timestamp.isoformat() if record.timestamp else None,
                "agent": AGENT_PATH_SEPARATOR.join(record.agent_path),
                "agent_path": list(record.agent_path),
                "server": server,
                "method": method,
                "call_count": 1,
                "result_chars": record.result_chars,
                "result_excluded": record.result_excluded,
            }
        )
    return sorted(
        activity,
        key=lambda row: (
            row["timestamp"] is None,
            row["timestamp"] or "",
            row["agent"],
            row["server"],
            row["method"],
        ),
    )
```

- [ ] **Step 5: Wire the helper into the existing single MCP collection pass**

In `cli/dashboard.py`, call the helper after `collect_per_session()` and before
rendering/JSON serialization:

```python
per_session, skipped = collect_per_session(
    selected,
    args.data_dir,
    track_mcp_call_sizes=args.track_mcp_call_sizes,
)
attach_session_mcp_activity(
    result,
    per_session,
    track_mcp_call_sizes=args.track_mcp_call_sizes,
)
usage = compute_tool_usage(
    per_session,
    track_mcp_call_sizes=args.track_mcp_call_sizes,
)
```

Do not add another transcript scan. The successful per-session tuples and
missing selected IDs already distinguish collected, empty, and unavailable
states (`src/claude_prospector/tool_collection.py:L460-L492`).

- [ ] **Step 6: Run MCP, CLI, and privacy regression tests**

Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_tool_collection.py tests/test_aggregator_tool_usage.py tests/test_dashboard_mcp_usage.py tests/test_dashboard_mcp_call_sizes.py tests/test_cli.py -q
```

Expected: all selected tests pass in disabled, call-only, and size-enabled
modes.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/claude_prospector/models.py src/claude_prospector/tool_collection.py src/claude_prospector/aggregator.py src/claude_prospector/cli/dashboard.py tests/unit/test_tool_collection.py tests/test_aggregator_tool_usage.py tests/test_dashboard_mcp_usage.py tests/test_dashboard_mcp_call_sizes.py
git commit -m "feat: retain opt-in MCP session activity (#310)"
```

---

### Task 4: Add executable client analytics helpers and CI coverage

**Files:**
- Modify: `src/claude_prospector/static/cp-utils.js`
- Create: `tests/fixtures/session-analytics/short-single-agent.json`
- Create: `tests/fixtures/session-analytics/long-concurrent-agents.json`
- Create: `tests/fixtures/session-analytics/deep-nested-agents.json`
- Create: `tests/js/session-analytics.test.js`
- Modify: `.github/workflows/ci.yml:31-49`

**Interfaces:**
- Consumes: Task 2/3 session JSON fields.
- Produces: `CP.sessionAnalytics` with `inRange`, `scopeSession`, `sumTokens`, `bucketResponses`, `usesExactBars`, `buildAgentTree`, `setSubtree`, `selectionState`, and `mergeLedger` for Tasks 6-8.

- [ ] **Step 1: Create committed fixtures and failing Node tests**

Each fixture is a complete session-summary object with exact totals. The long
fixture spans eight hours with overlapping root/child timestamps; dense-chart
tests derive 101 immutable copies from its responses. The deep fixture contains
repeated leaf names on different full paths. Use the exact field shape below;
additional response rows repeat the same schema, never omit token components:

`tests/fixtures/session-analytics/short-single-agent.json`:

```json
{
  "session_id": "short",
  "project": "project",
  "project_path": "/project",
  "start_time": "2026-09-13T10:00:00Z",
  "end_time": "2026-09-13T10:02:00Z",
  "duration_seconds": 120,
  "root_agent": "main",
  "agent_paths": [["main"]],
  "total_tokens": 60,
  "agent_activity": [
    {"timestamp":"2026-09-13T10:00:00Z","agent":"main","agent_path":["main"],"model":"sonnet","model_full":"claude-sonnet-5","effort":"low","effort_key":"low","input_tokens":1,"output_tokens":9,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":10},
    {"timestamp":"2026-09-13T10:01:00Z","agent":"main","agent_path":["main"],"model":"sonnet","model_full":"claude-sonnet-5","effort":"high","effort_key":"high","input_tokens":2,"output_tokens":18,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":20},
    {"timestamp":"2026-09-13T10:02:00Z","agent":"main","agent_path":["main"],"model":"opus","model_full":"claude-opus-5","effort":null,"effort_key":"unknown","input_tokens":3,"output_tokens":27,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":30}
  ],
  "skill_activity": [{"timestamp":"2026-09-13T10:01:00Z","agent":"main","agent_path":["main"],"skill":"python"}],
  "command_activity": [{"timestamp":"2026-09-13T10:00:00Z","agent":"main","agent_path":["main"],"name":"/compact"}],
  "session_facts": {"metadata": [], "effort_conflicts": 0},
  "mcp_collection": {"calls":"not_collected","result_sizes":"not_collected"},
  "mcp_activity": null
}
```

`tests/fixtures/session-analytics/long-concurrent-agents.json`:

```json
{
  "session_id": "long-concurrent",
  "project": "project",
  "project_path": "/project",
  "start_time": "2026-09-13T10:00:00Z",
  "end_time": "2026-09-13T18:00:00Z",
  "duration_seconds": 28800,
  "root_agent": "main",
  "agent_paths": [["main"],["main","worker"],["main","worker","explorer"]],
  "total_tokens": 1000,
  "agent_activity": [
    {"timestamp":"2026-09-13T10:00:00Z","agent":"main","agent_path":["main"],"model":"sonnet","model_full":"claude-sonnet-5","effort":"high","effort_key":"high","input_tokens":10,"output_tokens":90,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":100},
    {"timestamp":"2026-09-13T10:00:01Z","agent":"main→worker","agent_path":["main","worker"],"model":"opus","model_full":"claude-opus-5","effort":"max","effort_key":"max","input_tokens":20,"output_tokens":180,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":200},
    {"timestamp":"2026-09-13T10:00:01Z","agent":"main→worker→explorer","agent_path":["main","worker","explorer"],"model":"haiku","model_full":"claude-haiku-5","effort":"low","effort_key":"low","input_tokens":30,"output_tokens":270,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":300},
    {"timestamp":"2026-09-13T18:00:00Z","agent":"main","agent_path":["main"],"model":"sonnet","model_full":"claude-sonnet-5","effort":"high","effort_key":"high","input_tokens":40,"output_tokens":360,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":400}
  ],
  "skill_activity": [{"timestamp":"2026-09-13T10:00:01Z","agent":"main→worker","agent_path":["main","worker"],"skill":"python"}],
  "command_activity": [],
  "session_facts": {"metadata": [], "effort_conflicts": 0},
  "mcp_collection": {"calls":"collected","result_sizes":"not_collected"},
  "mcp_activity": [{"timestamp":"2026-09-13T10:00:01Z","agent":"main→worker→explorer","agent_path":["main","worker","explorer"],"server":"github","method":"get_issue","call_count":1,"result_chars":null,"result_excluded":false}]
}
```

`tests/fixtures/session-analytics/deep-nested-agents.json`:

```json
{
  "session_id": "deep",
  "project": "project",
  "project_path": "/project",
  "start_time": "2026-09-13T10:00:00Z",
  "end_time": "2026-09-13T10:00:04Z",
  "duration_seconds": 4,
  "root_agent": "main",
  "agent_paths": [["main"],["main","left"],["main","left","worker"],["main","right"],["main","right","worker"]],
  "total_tokens": 5,
  "agent_activity": [
    {"timestamp":"2026-09-13T10:00:00Z","agent":"main","agent_path":["main"],"model":"sonnet","model_full":"claude-sonnet-5","effort":"high","effort_key":"high","input_tokens":0,"output_tokens":1,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":1},
    {"timestamp":"2026-09-13T10:00:01Z","agent":"main→left","agent_path":["main","left"],"model":"sonnet","model_full":"claude-sonnet-5","effort":"high","effort_key":"high","input_tokens":0,"output_tokens":1,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":1},
    {"timestamp":"2026-09-13T10:00:02Z","agent":"main→left→worker","agent_path":["main","left","worker"],"model":"haiku","model_full":"claude-haiku-5","effort":"low","effort_key":"low","input_tokens":0,"output_tokens":1,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":1},
    {"timestamp":"2026-09-13T10:00:03Z","agent":"main→right","agent_path":["main","right"],"model":"sonnet","model_full":"claude-sonnet-5","effort":"high","effort_key":"high","input_tokens":0,"output_tokens":1,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":1},
    {"timestamp":"2026-09-13T10:00:04Z","agent":"main→right→worker","agent_path":["main","right","worker"],"model":"haiku","model_full":"claude-haiku-5","effort":"low","effort_key":"low","input_tokens":0,"output_tokens":1,"cache_read_tokens":0,"cache_creation_tokens":0,"total_tokens":1}
  ],
  "skill_activity": [],
  "command_activity": [],
  "session_facts": {"metadata": [], "effort_conflicts": 0},
  "mcp_collection": {"calls":"collected","result_sizes":"not_collected"},
  "mcp_activity": []
}
```

The tests load `cp-utils.js` in Node without browser dependencies:

```javascript
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

global.window = {};
require(path.resolve(__dirname, '../../src/claude_prospector/static/cp-utils.js'));
const A = window.CP.sessionAnalytics;

function sameTimestampEvents() {
  const timestamp = '2026-09-13T10:00:00Z';
  return {
    responses: [{timestamp, agent: 'main', total_tokens: 1}],
    skills: [{timestamp, agent: 'main', skill: 'python'}],
    commands: [{timestamp, agent: 'main', name: '/compact'}],
    mcp: [{timestamp, agent: 'main', server: 'github', method: 'get_issue'}],
  };
}

function rangeForResponse(response) {
  const start = Date.parse(response.timestamp);
  return {start, end: start + 1};
}

function effortBuckets() {
  return [
    {by_effort: {low: 2, high: 3}, total_tokens: 5},
    {by_effort: {low: 4, high: 1}, total_tokens: 5},
  ];
}

test('bucket totals reconcile for every effort series', () => {
  const session = require('../fixtures/session-analytics/long-concurrent-agents.json');
  const buckets = A.bucketResponses(session.agent_activity, {
    start: Date.parse(session.start_time),
    end: Date.parse(session.end_time) + 1,
    width: 600,
  });
  assert.equal(
    buckets.reduce((total, bucket) => total + bucket.total_tokens, 0),
    session.total_tokens,
  );
});

test('All ignores the brush and By time period applies it', () => {
  const session = require('../fixtures/session-analytics/short-single-agent.json');
  const active = new Set(['main']);
  assert.equal(A.scopeSession(session, active, 'all', {start: 0, end: 1}).responses.length, 3);
  assert.equal(
    A.scopeSession(session, active, 'period', {
      start: Date.parse(session.agent_activity[1].timestamp),
      end: Date.parse(session.agent_activity[2].timestamp),
    }).responses.length,
    1,
  );
});

test('disabling a child makes ancestors indeterminate', () => {
  const session = require('../fixtures/session-analytics/deep-nested-agents.json');
  const paths = session.agent_paths.map(parts => parts.join('→'));
  let active = new Set(paths);
  active = A.setSubtree(active, 'main→left', false, paths);
  assert.equal(A.selectionState(active, 'main', paths), 'indeterminate');
  assert.equal(active.has('main→left→worker'), false);
  assert.equal(active.has('main→right→worker'), true);
});
```

- [ ] **Step 2: Run Node tests and confirm the red state**

Run:

```bash
node --test tests/js/session-analytics.test.js
```

Expected: failure because `CP.sessionAnalytics` is undefined.

- [ ] **Step 3: Implement pure analytics helpers**

Add an IIFE-local `sessionAnalytics` object to `cp-utils.js`. Use half-open
ranges and the fixed bucket ladder from spec §5:

```javascript
const BUCKET_MS = [
  1000, 5000, 15000, 30000, 60000, 300000, 900000,
  1800000, 3600000, 10800000, 21600000, 43200000, 86400000,
];

function inRange(item, range) {
  const timestamp = Date.parse(item.timestamp);
  return Number.isFinite(timestamp) && timestamp >= range.start && timestamp < range.end;
}

function usesExactBars(responses, width) {
  return responses.length <= Math.max(1, Math.floor(width / 12));
}

function setSubtree(active, path, enabled, allPaths) {
  const next = new Set(active);
  const prefix = path + AGENT_PATH_SEP;
  for (const candidate of allPaths) {
    if (candidate === path || candidate.startsWith(prefix)) {
      if (enabled) next.add(candidate);
      else next.delete(candidate);
    }
  }
  return next;
}

function selectionState(active, path, allPaths) {
  const prefix = path + AGENT_PATH_SEP;
  const members = allPaths.filter(candidate => candidate === path || candidate.startsWith(prefix));
  const selected = members.filter(candidate => active.has(candidate)).length;
  if (selected === 0) return 'unchecked';
  if (selected === members.length) return 'checked';
  return 'indeterminate';
}

function sumTokens(responses) {
  return responses.reduce((totals, response) => {
    for (const key of [
      'input_tokens', 'output_tokens', 'cache_read_tokens',
      'cache_creation_tokens', 'total_tokens',
    ]) {
      totals[key] += Number(response[key] || 0);
    }
    return totals;
  }, {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    total_tokens: 0,
  });
}

function bucketResponses(responses, {start, end, width}) {
  const span = Math.max(1, end - start);
  const maxBuckets = Math.max(1, Math.floor(width / 6));
  const duration = BUCKET_MS.find(value => Math.ceil(span / value) <= maxBuckets)
    || Math.ceil(span / maxBuckets);
  const bucketCount = Math.max(1, Math.ceil(span / duration));
  const buckets = Array.from({length: bucketCount}, (_, index) => ({
    start: start + index * duration,
    end: Math.min(end, start + (index + 1) * duration),
    by_effort: {},
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    total_tokens: 0,
  }));
  for (const response of responses) {
    const timestamp = Date.parse(response.timestamp);
    if (!Number.isFinite(timestamp) || timestamp < start || timestamp >= end) continue;
    const index = Math.min(bucketCount - 1, Math.floor((timestamp - start) / duration));
    const bucket = buckets[index];
    for (const key of [
      'input_tokens', 'output_tokens', 'cache_read_tokens',
      'cache_creation_tokens', 'total_tokens',
    ]) {
      bucket[key] += Number(response[key] || 0);
    }
    const effort = response.effort_key || 'unknown';
    bucket.by_effort[effort] = (bucket.by_effort[effort] || 0)
      + Number(response.total_tokens || 0);
  }
  return buckets;
}

function scopeSession(session, activePaths, mode, range) {
  const active = row => activePaths.has(String(row.agent || ''));
  const scoped = rows => (rows || []).filter(row => active(row)
    && (mode !== 'period' || inRange(row, range)));
  return {
    responses: scoped(session.agent_activity),
    skills: scoped(session.skill_activity),
    commands: scoped(session.command_activity),
    mcp: session.mcp_activity === null ? null : scoped(session.mcp_activity),
  };
}
```

`bucketResponses()` chooses the smallest ladder duration whose bucket count is
within `Math.max(1, Math.floor(width / 6))`, falling back to
`Math.ceil(span/maxBuckets)`. It emits every bucket with a `by_effort` map and
all five token totals. `scopeSession()` applies full-path agent selection to
responses/Skills/Commands/MCP, then applies time only in `period` mode.
`buildAgentTree()` splits each full key once on `AGENT_PATH_SEP`, interns nodes
by accumulated full path, and returns root nodes whose `children` arrays are
sorted by full path:

```javascript
function buildAgentTree(paths) {
  const nodes = new Map();
  for (const path of [...paths].sort((left, right) =>
    left.split(AGENT_PATH_SEP).length - right.split(AGENT_PATH_SEP).length
      || left.localeCompare(right))) {
    const parts = path.split(AGENT_PATH_SEP);
    const node = nodes.get(path) || {path, label: parts.at(-1), children: []};
    nodes.set(path, node);
    if (parts.length > 1) {
      const parentPath = parts.slice(0, -1).join(AGENT_PATH_SEP);
      const parent = nodes.get(parentPath) || {
        path: parentPath,
        label: parts.at(-2),
        children: [],
      };
      nodes.set(parentPath, parent);
      if (!parent.children.some(child => child.path === path)) parent.children.push(node);
    }
  }
  for (const node of nodes.values()) {
    node.children.sort((left, right) => left.path.localeCompare(right.path));
  }
  return [...nodes.values()]
    .filter(node => !node.path.includes(AGENT_PATH_SEP))
    .sort((left, right) => left.path.localeCompare(right.path));
}
```

`mergeLedger()` tags the four scoped arrays with their kind and source ordinal,
then uses the spec §6 kind order solely for stable timestamp ties and places
missing timestamps last:

```javascript
function mergeLedger(scoped) {
  const kindOrder = {response: 0, skill: 1, command: 2, mcp: 3};
  const tagged = [];
  for (const [field, kind] of [
    ['responses', 'response'], ['skills', 'skill'],
    ['commands', 'command'], ['mcp', 'mcp'],
  ]) {
    for (const [ordinal, event] of (scoped[field] || []).entries()) {
      tagged.push({...event, kind, source_ordinal: ordinal});
    }
  }
  return tagged.sort((left, right) => {
    const leftTime = Date.parse(left.timestamp);
    const rightTime = Date.parse(right.timestamp);
    const leftMissing = !Number.isFinite(leftTime);
    const rightMissing = !Number.isFinite(rightTime);
    return Number(leftMissing) - Number(rightMissing)
      || (leftMissing ? 0 : leftTime - rightTime)
      || kindOrder[left.kind] - kindOrder[right.kind]
      || left.source_ordinal - right.source_ordinal;
  });
}
```

Export the object from `window.CP`. Do not access `document`, `Chart`, or
mutable view state in these helpers so Node can execute them directly.

- [ ] **Step 4: Expand Node tests to the complete client contract**

Add cases for:

```javascript
test('exact bars require twelve pixels per response', () => {
  assert.equal(A.usesExactBars(new Array(10).fill({}), 120), true);
  assert.equal(A.usesExactBars(new Array(11).fill({}), 120), false);
});

test('a dense long session stays continuous until the selected range narrows', () => {
  const fixture = require('../fixtures/session-analytics/long-concurrent-agents.json');
  const seed = fixture.agent_activity[0];
  const dense = Array.from({length: 101}, (_, index) => Object.freeze({
    ...seed,
    timestamp: new Date(Date.parse(fixture.start_time) + index * 1000).toISOString(),
  }));
  assert.equal(A.usesExactBars(dense, 1200), false);
  assert.equal(A.usesExactBars(dense.slice(0, 20), 1200), true);
  assert.equal(fixture.agent_activity.length, 4);
});

test('full paths with the same leaf stay independent', () => {
  const paths = ['main', 'main→left', 'main→left→worker', 'main→right', 'main→right→worker'];
  const active = A.setSubtree(new Set(paths), 'main→left→worker', false, paths);
  assert.equal(active.has('main→left→worker'), false);
  assert.equal(active.has('main→right→worker'), true);
});

test('ledger uses deterministic tie order without claiming causality', () => {
  const ledger = A.mergeLedger(sameTimestampEvents());
  assert.deepEqual(ledger.map(event => event.kind), ['response', 'skill', 'command', 'mcp']);
});
```

Also assert zero/not-collected/unavailable MCP distinctions and token-component
reconciliation on all three committed fixtures.

- [ ] **Step 5: Add Node to the existing CI test check**

The shared actions repository has no reusable Node setup action, so use the
official first-party action ([GitHub code search](https://github.com/search?q=repo%3Aglitchwerks%2Fgithub-actions+%22setup-node%22&type=code), fetched
2026-09-13; [actions/setup-node](https://github.com/actions/setup-node), fetched
2026-09-13). Add these steps to the existing `test` matrix, guarded to Ubuntu
so the pure platform-independent suite runs once without creating a new status
check or ruleset change:

```yaml
      - uses: actions/setup-node@v4
        if: matrix.os == 'ubuntu-latest'
        with:
          node-version: "22"
      - name: Client unit tests
        if: matrix.os == 'ubuntu-latest'
        run: node --test tests/js/session-analytics.test.js
```

The existing workflow already separates lint and test jobs and runs Python on
Linux and Windows (`.github/workflows/ci.yml:L10-L49`). Keep its read-only
permissions and existing matrix unchanged.

- [ ] **Step 6: Run client and related Python tests**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_phase2_shell.py tests/test_phase3_views.py -q
```

Expected: both commands pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/claude_prospector/static/cp-utils.js tests/fixtures/session-analytics tests/js/session-analytics.test.js .github/workflows/ci.yml
git commit -m "test: execute session analytics client contract (#310)"
```

---

### Task 5: Add hash routing and clickable session rows

**Files:**
- Modify: `src/claude_prospector/static/views/economics-basic.js:345-356,450-480`
- Modify: `src/claude_prospector/static/views/layout-b-diag.js:1091-1118`
- Create: `src/claude_prospector/static/views/session-detail.js`
- Modify: `src/claude_prospector/renderer.py:116-129`
- Modify: `src/claude_prospector/templates/dashboard.html:339-427`
- Modify: `tests/test_phase2_shell.py`
- Modify: `tests/test_phase3_views.py`
- Create: `tests/test_session_detail_routing.py`
- Modify: `tests/js/session-analytics.test.js`

**Interfaces:**
- Consumes: `session_id` from existing session summaries.
- Produces: `CP.sessionAnalytics.parseRoute(hash)`, a minimal `renderSessionDetail(container, session, routeState) -> cleanupFunction`, `economy:open-session`, `economy:close-session`, and the shell route lifecycle expanded by Task 6.

- [ ] **Step 1: Write failing route and row-link tests**

Add Node cases for strict hash parsing and rendered-source tests for history
handling and both session lists:

```javascript
test('parseRoute accepts one encoded session key only', () => {
  assert.deepEqual(A.parseRoute('#session=abc%2F123'), {kind: 'session', sessionId: 'abc/123'});
  assert.deepEqual(A.parseRoute('#session='), {kind: 'not-found', sessionId: ''});
  assert.deepEqual(A.parseRoute('#unknown=value'), {kind: 'dashboard'});
});
```

```python
def test_both_session_lists_dispatch_open_session() -> None:
    basic = _read_view("economics-basic.js")
    detail = _read_view("layout-b-diag.js")
    assert "economy:open-session" in basic
    assert "economy:open-session" in detail
    assert "encodeURIComponent(String(s.session_id" in basic
    assert "encodeURIComponent(String(s.session_id" in detail


def test_shell_handles_direct_hash_back_and_unknown_session(tmp_path: Path) -> None:
    html = _render_html(tmp_path)
    assert "history.pushState" in html
    assert "popstate" in html
    assert "hashchange" in html
    assert "Session not found in this dashboard" in html


def test_minimal_session_view_is_packaged_and_inlined(tmp_path: Path) -> None:
    asset = resources.files("claude_prospector") / "static" / "views" / "session-detail.js"
    assert asset.is_file()
    assert "function renderSessionDetail" in _render_html(tmp_path)
```

Define the Task 5 Python test helpers at the top of
`tests/test_session_detail_routing.py`:

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_view(name: str) -> str:
    return (_REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / name).read_text(
        encoding="utf-8"
    )


def _render_html(tmp_path: Path) -> str:
    output = tmp_path / "dashboard.html"
    render(AggregateResult(), output_path=output, open_browser=False)
    return output.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run route tests and confirm the red state**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_session_detail_routing.py tests/test_phase2_shell.py -q
```

Expected: failures for missing route helper and session events.

- [ ] **Step 3: Add encoded session controls to both existing views**

Render each row as a native button with an encoded data attribute. Dynamic
labels continue through `CP.esc()`:

```javascript
const encodedSessionId = encodeURIComponent(String(s.session_id || ''));
return `
  <button type="button" class="session-row" data-session-id="${encodedSessionId}">
    <span class="time">${CP.esc(CP.fmtRelTime(s.start_time))}</span>
    <span class="proj">${CP.esc(s.project || 'Unknown project')}</span>
    <span class="tok">${CP.esc(CP.fmtTokens(s.total_tokens))}</span>
  </button>`;
```

Delegate one click handler from each view container:

```javascript
const root = container;
root.addEventListener('click', event => {
  const row = event.target.closest('[data-session-id]');
  if (!row) return;
  root.dispatchEvent(new CustomEvent('economy:open-session', {
    bubbles: true,
    detail: {
      sessionId: decodeURIComponent(row.dataset.sessionId),
      returnView: 'detail',
      returnState: {period: state.period, tab: state.tab},
    },
  }));
});
```

Overview sends `returnView: 'basic'` without view state. Breakdown restores its
period and tab through an optional initial-state argument. Preserve keyboard
activation through native button behavior.

Change Breakdown's existing entry point and state initialization to accept
only values already supported by its period and tab controls
(`src/claude_prospector/static/views/layout-b-diag.js:L891-L896`,
`src/claude_prospector/static/views/layout-b-diag.js:L996-L1019`):

```javascript
window.renderLayoutBDiag = function renderLayoutBDiag(root, initialState = {}) {
```

Replace the current one-line state initialization with:

```javascript
const validPeriods = new Set(['5h', '24h', '7d', '30d', 'all']);
const validTabs = new Set(['burn', 'sessions', 'movers', 'efficiency']);
const state = {
  period: validPeriods.has(initialState.period) ? initialState.period : '7d',
  tab: validTabs.has(initialState.tab) ? initialState.tab : 'burn',
};
```

Those are the only two edits inside `renderLayoutBDiag()`; its stylesheet,
compute, render, and listener bodies remain byte-for-byte unchanged.

Pass `history.state.returnState` only when `_renderView()` restores the
Breakdown view. This preserves its selected period/tab without accepting
arbitrary route-provided values
(`src/claude_prospector/static/views/layout-b-diag.js:L987-L996`).

- [ ] **Step 4: Add the minimal view lifecycle and implement the shell router**

Create a small working `session-detail.js` target before wiring the router:

```javascript
(function () {
  function renderSessionDetail(container, session, routeState) {
    const section = document.createElement('section');
    section.className = 'session-detail';
    const back = document.createElement('button');
    back.type = 'button';
    back.textContent = 'Back to dashboard';
    back.addEventListener('click', routeState.close);
    const heading = document.createElement('h2');
    heading.tabIndex = -1;
    heading.textContent = `Session ${String(session.session_id)}`;
    section.append(back, heading);
    container.replaceChildren(section);
    heading.focus();
    return () => container.replaceChildren();
  }
  window.renderSessionDetail = renderSessionDetail;
})();
```

Wire it through
`session_detail_js=_read_static("views/session-detail.js")` in `renderer.py`
and inline it with the other packaged views. Then add `parseRoute()` to Task
4's pure helper object. In the template, track the active dashboard view, find
sessions by exact string ID, and render routes:

```javascript
function parseRoute(hash) {
  const params = new URLSearchParams(String(hash || '').replace(/^#/, ''));
  const entries = [...params.entries()];
  if (entries.length !== 1 || entries[0][0] !== 'session') {
    return {kind: 'dashboard'};
  }
  const sessionId = entries[0][1];
  return sessionId
    ? {kind: 'session', sessionId}
    : {kind: 'not-found', sessionId: ''};
}

function _renderSessionNotFound(sessionId) {
  const section = document.createElement('section');
  section.setAttribute('role', 'status');
  const heading = document.createElement('h2');
  heading.tabIndex = -1;
  heading.textContent = 'Session not found in this dashboard';
  const message = document.createElement('p');
  message.textContent = sessionId
    ? `No in-scope session matches ${sessionId}.`
    : 'The session identifier is empty.';
  const back = document.createElement('button');
  back.type = 'button';
  back.textContent = 'Back to session list';
  back.addEventListener('click', () =>
    window.dispatchEvent(new CustomEvent('economy:close-session')));
  section.append(heading, message, back);
  _container.replaceChildren(section);
  heading.focus();
}
```

```javascript
let _activeView = 'basic';
let _sessionCleanup = null;

function _renderRoute() {
  const route = CP.sessionAnalytics.parseRoute(window.location.hash);
  if (route.kind === 'dashboard') {
    setView((history.state && history.state.returnView) || _activeView || 'basic');
    return;
  }
  if (route.kind === 'not-found') {
    _container.replaceChildren();
    _renderSessionNotFound(route.sessionId);
    return;
  }
  const session = (window.DATA.sessions || []).find(
    item => String(item.session_id) === route.sessionId,
  );
  _container.replaceChildren();
  if (!session) {
    _renderSessionNotFound(route.sessionId);
    return;
  }
  _sessionCleanup = renderSessionDetail(_container, session, {
    close: () => window.dispatchEvent(new CustomEvent('economy:close-session')),
  });
}
```

`economy:open-session` calls `history.pushState()` with return view/state and an
encoded `#session=` URL, then calls `_renderRoute()` because `pushState` emits
no navigation event. `popstate` and `hashchange` call `_renderRoute()`.
`economy:close-session` uses `history.back()` only when the current history
state was created by the router; otherwise it clears the hash with
`replaceState()` and restores Overview. Call the prior view cleanup before
rendering a new route.

- [ ] **Step 5: Run route, view, snapshot, and client tests**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_session_detail_routing.py tests/test_phase2_shell.py tests/test_phase3_views.py tests/test_dashboard_snapshot.py -q
```

Expected: all selected tests pass after intentional snapshot updates.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/claude_prospector/static/cp-utils.js src/claude_prospector/static/views/economics-basic.js src/claude_prospector/static/views/layout-b-diag.js src/claude_prospector/static/views/session-detail.js src/claude_prospector/renderer.py src/claude_prospector/templates/dashboard.html tests/js/session-analytics.test.js tests/test_session_detail_routing.py tests/test_phase2_shell.py tests/test_phase3_views.py tests/test_dashboard_snapshot.py tests/fixtures/dashboard_snapshot_pre_refactor.json
git commit -m "feat: route dashboard sessions by hash (#310)"
```

---

### Task 6: Build the session page shell, scope control, and recursive agent filter

**Files:**
- Modify: `src/claude_prospector/static/views/session-detail.js`
- Create: `tests/test_session_detail_view.py`
- Modify: `tests/js/session-analytics.test.js`

**Interfaces:**
- Consumes: Task 4 `CP.sessionAnalytics`, Task 5 router callbacks, and Task 2 session payload.
- Produces: `renderSessionDetail(container, session, routeState) -> cleanupFunction`, stable DOM hooks (`data-session-scope`, `data-agent-path`, `data-session-panel`), and one render state consumed by Tasks 7-8.

- [ ] **Step 1: Write failing resource, rendering, accessibility, and state tests**

Pin the required semantic controls and expanded renderer contract:

```python
def test_session_page_has_scope_and_recursive_agent_controls(tmp_path: Path) -> None:
    _render_html(tmp_path, _session_result())
    source = _session_detail_source()
    assert "Session analytics scope" in source
    assert "['all', 'period']" in source
    assert "setAttribute('role', 'tree')" in source
    assert "indeterminate" in source
    assert "No agents selected" in source
```

In `tests/test_session_detail_view.py`, reuse the same `_render_html()` shape
from Task 5 but accept an optional `AggregateResult`. Define `_session_result()`
without parser dependencies:

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _session_detail_source() -> str:
    path = (
        _REPO_ROOT
        / "src"
        / "claude_prospector"
        / "static"
        / "views"
        / "session-detail.js"
    )
    return path.read_text(encoding="utf-8")


def _render_html(
    tmp_path: Path,
    result: AggregateResult | None = None,
) -> str:
    output = tmp_path / "dashboard.html"
    render(result or AggregateResult(), output_path=output, open_browser=False)
    return output.read_text(encoding="utf-8")


def _session_result() -> AggregateResult:
    result = AggregateResult(total_tokens=10, total_messages=1, total_sessions=1)
    result.sessions = [
        {
            "session_id": "session-1",
            "project": "project",
            "project_path": "/project",
            "start_time": "2026-09-13T10:00:00+00:00",
            "end_time": "2026-09-13T10:01:00+00:00",
            "duration_seconds": 60,
            "root_agent": "main",
            "agent_paths": [["main"]],
            "agent_activity": [{
                "timestamp": "2026-09-13T10:00:00+00:00",
                "agent": "main",
                "agent_path": ["main"],
                "model": "sonnet",
                "model_full": "claude-sonnet-5",
                "effort": "high",
                "effort_key": "high",
                "input_tokens": 1,
                "output_tokens": 2,
                "cache_read_tokens": 3,
                "cache_creation_tokens": 4,
                "total_tokens": 10,
            }],
            "skill_activity": [],
            "command_activity": [],
            "session_facts": {"metadata": [], "effort_conflicts": 0},
            "mcp_collection": {"calls": "not_collected", "result_sizes": "not_collected"},
            "mcp_activity": None,
        }
    ]
    return result
```

Add Node state tests proving initial full selection, parent subtree toggles,
child-only disabling, and a zero-selection reset.

- [ ] **Step 2: Run the new view tests and confirm the red state**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_session_detail_view.py tests/test_phase3_views.py -q
```

Expected: failures for missing scope and recursive-agent controls.

- [ ] **Step 3: Expand the view lifecycle around one immutable source session**

Inside the existing view IIFE, bind `const A = CP.sessionAnalytics;` once and
use this public lifecycle:

```javascript
function renderSessionDetail(container, session, routeState) {
  const pathArrays = (session.agent_paths && session.agent_paths.length)
    ? session.agent_paths
    : (session.agent_activity || []).map(item =>
        item.agent_path || String(item.agent || '').split(CP.AGENT_PATH_SEP));
  const allPaths = [...new Set(pathArrays.map(parts => parts.join(CP.AGENT_PATH_SEP)))]
    .filter(Boolean);
  const activityTimes = (session.agent_activity || [])
    .map(item => Date.parse(item.timestamp))
    .filter(Number.isFinite);
  const recordedStart = Date.parse(session.start_time);
  const recordedEnd = Date.parse(session.end_time);
  const sessionStart = Number.isFinite(recordedStart)
    ? recordedStart
    : Math.min(...activityTimes);
  const sessionEnd = Number.isFinite(recordedEnd)
    ? recordedEnd + 1
    : Math.max(...activityTimes) + 1;
  const state = {
    scope: 'all',
    range: {
      start: sessionStart,
      end: sessionEnd,
    },
    hasTimeline: Number.isFinite(sessionStart) && Number.isFinite(sessionEnd),
    activePaths: new Set(allPaths),
    expanded: new Set(),
  };
  let disposed = false;

  function render() {
    if (disposed) return;
    const scoped = CP.sessionAnalytics.scopeSession(
      session,
      state.activePaths,
      state.scope,
      state.range,
    );
    container.replaceChildren(buildSessionPage(session, state, scoped));
    bindControls(container, state, render, routeState);
  }

  render();
  return () => {
    disposed = true;
    CP.destroyChartsByPrefix('session-');
    container.replaceChildren();
  };
}
```

Keep `window.renderSessionDetail = renderSessionDetail` from Task 5 and preserve
the same cleanup signature so the router needs no change.

- [ ] **Step 4: Render the scan-first semantic shell**

Create every static or transcript-derived node through this helper; passing
`undefined` omits optional class/text assignments:

```javascript
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}
```

The header includes a Back button, escaped project/session labels, start/end,
duration, response count, and current active-path count. Add native radio
inputs for `All` and `By time period`, a scoped-total live region, and empty
states. Never mutate the source `session` object.

Build the agent tree from `CP.sessionAnalytics.buildAgentTree()`. Each node uses
a native checkbox; after rendering set its DOM property:

```javascript
const selection = A.selectionState(state.activePaths, node.path, allPaths);
checkbox.checked = selection === 'checked';
checkbox.indeterminate = selection === 'indeterminate';
checkbox.dataset.agentPath = encodeURIComponent(node.path);
```

On change, call `setSubtree()`, rerender every scoped panel, and preserve focus
by encoded full path. Provide `Select all` when the active set is empty.

Build scope radios from the literal mode array `['all', 'period']`, set the
fieldset's `aria-label` to `Session analytics scope`, and set the agent
container with `tree.setAttribute('role', 'tree')`; these exact hooks are the
source contract asserted above.

- [ ] **Step 5: Run view, resource, renderer, and client state tests**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_session_detail_view.py tests/test_phase3_views.py tests/test_renderer.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add src/claude_prospector/static/views/session-detail.js tests/test_session_detail_view.py tests/js/session-analytics.test.js
git commit -m "feat: add session analytics view shell (#310)"
```

---

### Task 7: Add stacked overview, scoped bars, brush, and concurrent agent tracks

**Files:**
- Modify: `src/claude_prospector/static/views/session-detail.js`
- Modify: `src/claude_prospector/static/cp-utils.js`
- Modify: `tests/js/session-analytics.test.js`
- Modify: `tests/test_session_detail_view.py`

**Interfaces:**
- Consumes: Task 6 view state and Task 4 buckets/scoped response sets.
- Produces: `renderOverviewSvg`, `renderScopedDetail`, `renderAgentTracks`, and accessible range controls; updates `state.range` without changing the overview domain.

- [ ] **Step 1: Add failing chart-mode, stacking, range, and track tests**

Extend Node tests with shared cumulative boundaries and period-only brush
effects:

```javascript
test('stack boundaries share one baseline at every bucket', () => {
  const layers = A.stackEffortBuckets(effortBuckets());
  for (let index = 0; index < layers[0].upper.length; index += 1) {
    assert.equal(layers[1].lower[index], layers[0].upper[index]);
  }
});

test('moving the brush changes period detail but not all detail', () => {
  const session = require('../fixtures/session-analytics/short-single-agent.json');
  const active = new Set(['main']);
  const firstRange = rangeForResponse(session.agent_activity[0]);
  const lastRange = rangeForResponse(session.agent_activity[2]);
  assert.deepEqual(
    A.scopeSession(session, active, 'all', firstRange).responses,
    A.scopeSession(session, active, 'all', lastRange).responses,
  );
  assert.notDeepEqual(
    A.scopeSession(session, active, 'period', firstRange).responses,
    A.scopeSession(session, active, 'period', lastRange).responses,
  );
});
```

Add source/render assertions for a full-domain overview, `Zoom further for
per-response bars`, focusable exact bars, labeled range inputs, and one track
row per full path.

- [ ] **Step 2: Run chart tests and confirm the red state**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_session_detail_view.py -q
```

Expected: failures for stacking and timeline renderers.

- [ ] **Step 3: Implement common-boundary effort stacking**

Add `stackEffortBuckets(buckets)` to `CP.sessionAnalytics`. Order known effort
keys as `low`, `medium`, `high`, `max`, `unknown`; append future keys
lexicographically. Every layer reuses the same x index and prior cumulative
upper boundary:

```javascript
function orderedEffortKeys(buckets) {
  const known = ['low', 'medium', 'high', 'max', 'unknown'];
  const observed = new Set(
    buckets.flatMap(bucket => Object.keys(bucket.by_effort || {})),
  );
  const ordered = known.filter(key => observed.delete(key));
  return ordered.concat([...observed].sort((left, right) => left.localeCompare(right)));
}

function stackEffortBuckets(buckets) {
  const keys = orderedEffortKeys(buckets);
  const baseline = new Array(buckets.length).fill(0);
  return keys.map(key => {
    const lower = baseline.slice();
    const upper = buckets.map((bucket, index) => {
      baseline[index] += (bucket.by_effort[key] || 0);
      return baseline[index];
    });
    return {key, lower, upper};
  });
}
```

The SVG path builder creates each band from its upper points left-to-right and
lower points right-to-left. Do not smooth layers independently. Add labeled
legend swatches/patterns and a textual totals table.

- [ ] **Step 4: Implement the brush and scoped detail chart**

Keep the overview x-domain fixed at `session.start_time` through
`session.end_time`. Add two labeled range inputs sharing integer response/time
steps and a pointer brush overlay. Normalize every change through:

```javascript
function setRange(start, end) {
  state.range = {
    start: Math.max(sessionStart, Math.min(start, end - 1)),
    end: Math.min(sessionEnd, Math.max(end, start + 1)),
  };
  render();
}
```

In `All`, the scoped detail receives every active response. In `period`, it
receives only `inRange()` responses. Use `usesExactBars()` to choose focusable
per-response `<button>` bars or adaptive bucket SVG. Each bar's accessible name
contains timestamp, full model, effort/Unknown, path, and all token components.

- [ ] **Step 5: Render one concurrent track per exact agent path**

Create a track row for every `session.agent_paths` entry. Plot each active
response independently at its timestamp; overlapping x positions across rows
remain visible. Encode model by marker shape/label, effort by fill/pattern, and
token magnitude by bounded marker size. The track's checkbox delegates to the
Task 6 tree state so clicking an active child disables that child and its
descendants without affecting siblings (spec §§5.5-5.6; #310).

- [ ] **Step 6: Run client/view tests and manually inspect all three fixtures**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_session_detail_view.py tests/test_dashboard_snapshot.py -q
./.venv/Scripts/python.exe -m claude_prospector dashboard --output .pytest_cache/session-analytics.html --no-open
```

Open `.pytest_cache/session-analytics.html` and verify: shared stacked
boundaries have no gaps, All ignores the brush, By time period follows it,
dense ranges show the zoom message, narrow ranges show exact focusable bars,
and concurrent agent tracks do not collapse into one ribbon.

- [ ] **Step 7: Commit Task 7**

```bash
git add src/claude_prospector/static/views/session-detail.js src/claude_prospector/static/cp-utils.js tests/js/session-analytics.test.js tests/test_session_detail_view.py tests/test_dashboard_snapshot.py tests/fixtures/dashboard_snapshot_pre_refactor.json
git commit -m "feat: visualize session effort over time (#310)"
```

---

### Task 8: Add complete expandable details and deterministic event ledger

**Files:**
- Modify: `src/claude_prospector/static/views/session-detail.js`
- Modify: `src/claude_prospector/static/cp-utils.js`
- Modify: `tests/js/session-analytics.test.js`
- Modify: `tests/test_session_detail_view.py`
- Modify: `tests/test_dashboard_mcp_usage.py`

**Interfaces:**
- Consumes: Task 4 `scopeSession()`/`mergeLedger()`, Task 2 detail arrays, and Task 3 MCP state.
- Produces: complete Agent hierarchy, Skills, Commands, Session facts, MCP, response table, and event ledger panels with no truncation.

- [ ] **Step 1: Write failing full-detail and missing-state tests**

Pin all panel names, native disclosure semantics, untruncated counts, scoped
records, and exact MCP copy:

```python
def test_every_detail_panel_has_complete_native_disclosure(tmp_path: Path) -> None:
    _render_html(tmp_path, _session_result())
    source = _session_detail_source()
    for panel in ("agents", "skills", "commands", "facts", "mcp", "responses", "ledger"):
        assert f"'{panel}'" in source
    assert "details.dataset.sessionPanel = name" in source
    assert "element('details'" in source
    assert ".slice(0," not in source


def test_mcp_copy_distinguishes_collection_states() -> None:
    source = _session_detail_source()
    assert "Not collected" in source
    assert "Unavailable" in source
    assert "0 calls" in source
    assert "Estimated result size" in source
```

Node tests verify that disabled child events disappear from Skills/MCP/ledger,
period scope filters every timestamped event, All ignores the period, root
commands follow root selection, and missing-time MCP calls appear only in All.

- [ ] **Step 2: Run detail tests and confirm the red state**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_session_detail_view.py tests/test_dashboard_mcp_usage.py -q
```

Expected: missing-panel and copy-contract failures.

- [ ] **Step 3: Implement scan-first disclosure panels**

Use native `<details>`/`<summary>` elements. Summary text contains the exact
current count or state; expanded tables iterate the entire scoped array:

```javascript
const PANEL_ORDER = [
  'agents', 'skills', 'commands', 'facts', 'mcp', 'responses', 'ledger',
];

function buildActivityPanel(name, label, rows, renderRow) {
  const details = element('details', 'session-panel');
  details.dataset.sessionPanel = name;
  const summary = element('summary', 'session-panel-summary', `${label} · ${rows.length}`);
  const body = element('div', 'session-panel-body');
  for (const row of rows) body.append(renderRow(row));
  details.append(summary, body);
  return details;
}

function statusPanel(name, label, status) {
  const details = element('details', 'session-panel');
  details.dataset.sessionPanel = name;
  details.append(
    element('summary', 'session-panel-summary', `${label} · ${status}`),
    element('p', 'session-panel-status', status),
  );
  return details;
}
```

Render every dynamic cell with `textContent`. The response table includes
timestamp, full/normalized model, effort, full agent path, input, output, cache
read, cache creation, and total. The fact table lists every metadata value with
first-seen time and agent paths, plus effort conflict count. It never selects a
single branch/version when multiple values were recorded (spec §§3.1, 3.4).

- [ ] **Step 4: Implement MCP state and size-proxy presentation**

Branch on `session.mcp_collection.calls` before reading `mcp_activity`:

```javascript
const mcpState = session.mcp_collection || {
  calls: 'not_collected',
  result_sizes: 'not_collected',
};
if (mcpState.calls === 'not_collected') {
  return statusPanel('mcp', 'MCP', 'Not collected');
}
if (mcpState.calls === 'unavailable') {
  const warning = mcpState.warning === 'transcript_unavailable'
    ? 'Unavailable · Transcript unavailable'
    : 'Unavailable';
  return statusPanel('mcp', 'MCP', warning);
}
const mcpRows = Array.isArray(scoped.mcp) ? scoped.mcp : [];
if (mcpRows.length === 0) return statusPanel('mcp', 'MCP', '0 calls');

function formatResultSize(call) {
  if (mcpState.result_sizes !== 'collected') return null;
  if (call.result_excluded) return 'Excluded by collection limit';
  if (Number.isFinite(call.result_chars)) {
    return `Estimated result size: ${call.result_chars} characters`;
  }
  return 'Estimated result size: Unavailable';
}
```

Group compact MCP summaries by escaped `server.method`, but expanded rows and
the ledger retain each call. Append the non-null `formatResultSize()` result to
each expanded call row. This distinguishes measured zero, excluded, and
unavailable values while hiding the column when size collection did not run.
Never show raw tool names or contents (spec §§3.5, 9).

- [ ] **Step 5: Implement the complete deterministic ledger**

Call `mergeLedger(scoped)` and render every event. Missing timestamps sort last
and display `Time not recorded`; in `By time period` they are excluded because
their inclusion cannot be proven. Tie order is response, Skill, Command, MCP,
then source ordinal. Include a visible note that equal timestamps do not imply
causality (spec §6).

- [ ] **Step 6: Run complete client, detail, MCP, renderer, and snapshot tests**

Run:

```bash
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_session_detail_view.py tests/test_dashboard_mcp_usage.py tests/test_dashboard_mcp_call_sizes.py tests/test_renderer.py tests/test_dashboard_snapshot.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 8**

```bash
git add src/claude_prospector/static/views/session-detail.js src/claude_prospector/static/cp-utils.js tests/js/session-analytics.test.js tests/test_session_detail_view.py tests/test_dashboard_mcp_usage.py tests/test_dashboard_snapshot.py tests/fixtures/dashboard_snapshot_pre_refactor.json
git commit -m "feat: expand deterministic session details (#310)"
```

---

### Task 9: Document, verify, and prepare the implementation for review

**Files:**
- Modify: `README.md:75-89,239-306`
- Modify: `tests/test_e2e.py`
- Modify: `tests/test_template_resource.py`
- Modify: `tests/test_phase3_views.py`
- Modify: `tests/test_dashboard_snapshot.py`
- Modify: `tests/fixtures/dashboard_snapshot_pre_refactor.json`

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: user/developer documentation, full regression coverage, rendered manual artifact, and final feature commit.

- [ ] **Step 1: Add failing end-to-end and package-resource assertions**

Create an end-to-end test that parses a root plus nested child, aggregates it,
attaches MCP data, renders HTML, and asserts exact response totals and embedded
session activity:

```python
def _write_nested_effort_corpus(tmp_path: Path) -> Path:
    data_dir = tmp_path / "claude-data"
    project_dir = data_dir / "projects" / "project"
    project_dir.mkdir(parents=True)
    session_id = "session-e2e"
    root_path = project_dir / f"{session_id}.jsonl"
    root_entry = {
        "type": "assistant",
        "timestamp": "2026-09-13T10:00:00Z",
        "effort": "high",
        "message": {
            "id": "root-message",
            "model": "claude-sonnet-5",
            "content": [{
                "type": "tool_use",
                "id": "root-mcp",
                "name": "mcp__github__get_issue",
                "input": {},
            }],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 2,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 4,
            },
        },
    }
    root_path.write_text(json.dumps(root_entry), encoding="utf-8")

    child_dir = project_dir / session_id / "subagents"
    child_dir.mkdir(parents=True)
    (child_dir / "agent-child.meta.json").write_text(
        json.dumps({"agentType": "worker"}),
        encoding="utf-8",
    )
    child_entry = {
        "type": "assistant",
        "timestamp": "2026-09-13T10:00:01Z",
        "effort": "low",
        "message": {
            "id": "child-message",
            "model": "claude-haiku-5",
            "content": [{"type": "text", "text": "excluded"}],
            "usage": {
                "input_tokens": 5,
                "output_tokens": 6,
                "cache_read_input_tokens": 7,
                "cache_creation_input_tokens": 8,
            },
        },
    }
    (child_dir / "agent-child.jsonl").write_text(
        json.dumps(child_entry),
        encoding="utf-8",
    )
    return data_dir


def test_session_effort_analytics_survives_parse_to_render(tmp_path: Path) -> None:
    data_dir = _write_nested_effort_corpus(tmp_path)
    sessions = parse_sessions(data_dir)
    result = aggregate(sessions)
    per_session, _ = collect_per_session(sessions, data_dir)
    attach_session_mcp_activity(result, per_session, track_mcp_call_sizes=False)
    output = render(result, tmp_path / "dashboard.html", open_browser=False)
    html = output.read_text(encoding="utf-8")
    assert '"effort_key": "high"' in html
    assert '"agent_path": [' in html
    assert '"calls": "collected"' in html
    assert sum(row["total_tokens"] for row in result.sessions[0]["agent_activity"]) == result.sessions[0]["total_tokens"]
```

Add package-resource assertions for `session-detail.js` and all three committed
client fixtures.

- [ ] **Step 2: Run the new end-to-end checks and confirm any missing coverage**

Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_e2e.py tests/test_template_resource.py tests/test_phase3_views.py -q
```

Expected before documentation/snapshot updates: the new behavioral test passes;
resource or snapshot assertions identify any omitted packaging/wiring.

- [ ] **Step 3: Update README behavior and privacy documentation**

Extend the existing dashboard feature list and CLI MCP section with this exact
user contract:

```markdown
- **Session analytics** — open a session row for a full recorded-effort timeline,
  exact per-response token details, and independently filterable nested-agent tracks.
  `All` keeps details scoped to the complete session represented in the dashboard;
  `By time period` scopes them to the selected interval.

MCP session detail follows the same opt-ins as the global MCP report. Without
`--track-mcp-calls` (or the separate result-size flag), the session page says
**Not collected**; it does not report zero calls. The page never stores prompts,
tool arguments, or tool-result content. Result sizes remain estimates and appear
only when `--track-mcp-call-sizes` is enabled.
```

Add the contributor command `node --test tests/js/session-analytics.test.js`
and state that Node 22 is used by CI. Do not change installation prerequisites
for dashboard users because generated reports remain self-contained (spec §12;
`README.md:L75-L89`, `README.md:L239-L306`).

- [ ] **Step 4: Run formatters and focused verification**

Run:

```bash
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format --check .
node --test tests/js/session-analytics.test.js
./.venv/Scripts/python.exe -m pytest tests/test_models.py tests/test_parser.py tests/test_aggregator.py tests/test_aggregator_tool_usage.py tests/unit/test_tool_collection.py tests/test_dashboard_mcp_usage.py tests/test_dashboard_mcp_call_sizes.py tests/test_session_detail_payload.py tests/test_session_detail_routing.py tests/test_session_detail_view.py tests/test_renderer.py tests/test_phase2_shell.py tests/test_phase3_views.py tests/test_dashboard_snapshot.py tests/test_e2e.py -q
```

Expected: every command exits zero.

- [ ] **Step 5: Render and complete the browser accessibility smoke checklist**

Run:

```bash
./.venv/Scripts/python.exe -m claude_prospector dashboard --output .pytest_cache/session-analytics-final.html --no-open
```

Open `.pytest_cache/session-analytics-final.html` and verify all of the
following on available short, long, and nested sessions; the three committed
fixtures cover any shape absent from the local corpus:

- direct `#session=` load, Back, and unknown-ID return route;
- whole-session overview stays fixed while the brush moves;
- `All` ignores and `By time period` follows the brush;
- exact bars appear only at legible density and remain keyboard focusable;
- stacked effort bands share boundaries with no visual gaps;
- child toggles update parent indeterminate state and leave siblings active;
- all panels expand to complete rows with no top-N truncation;
- MCP disabled/zero/unavailable/size-enabled states use distinct copy;
- focus is visible, route headings receive focus, and charts have text tables;
- narrow viewport controls remain usable and detailed tables scroll horizontally.

The default artifact must show `Not collected`. Only after explicit user
approval for the MCP privacy opt-in, generate a second artifact with:

```bash
./.venv/Scripts/python.exe -m claude_prospector dashboard --output .pytest_cache/session-analytics-mcp.html --no-open --track-mcp-calls
```

The automated fixture tests remain the release gate for collected-zero,
collected-call, unavailable, and result-size-enabled states when that approval
is not granted.

Record the artifact path and checklist result in the eventual PR body. Do not
commit either `.pytest_cache` artifact.

- [ ] **Step 6: Run the full Python suite with a worktree-local temp directory**

Run:

```bash
./.venv/Scripts/python.exe -m pytest --basetemp=.pytest_cache/final-temp
```

Expected: all tests pass. The pre-implementation Windows baseline at commit
`be75a23` produced 1,034 passes, 2 skips, and one timeout in
`test_valid_flag_import_fails_deletes_flag_and_emits_banner`; if that same
unrelated timeout recurs, rerun it alone, report it explicitly, and require
green CI before merge. Do not describe the full suite as passing unless the
fresh output has zero failures.

- [ ] **Step 7: Audit referenced artifacts and commit Task 9**

Verify every committed path named by this plan exists at `HEAD`, including the
new view and three fixtures:

```bash
git ls-tree -r --name-only HEAD | rg "session-detail.js|tests/fixtures/session-analytics|tests/js/session-analytics.test.js"
git diff main...HEAD --stat
git status --short
```

Reconcile the diff stat with Tasks 1-9, then commit documentation and final
test/snapshot updates:

```bash
git add README.md tests/test_e2e.py tests/test_template_resource.py tests/test_phase3_views.py tests/test_dashboard_snapshot.py tests/fixtures/dashboard_snapshot_pre_refactor.json
git commit -m "docs: document session effort analytics (#310)"
```

After this commit, invoke `superpowers:requesting-code-review`, address every
actionable finding, and follow `superpowers:finishing-a-development-branch`.
The PR body must include `Closes #310` and the required Codex attribution.
