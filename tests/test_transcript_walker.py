"""Tests for the shared transcript walker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_prospector.transcript_walker import (
    AgentTranscript,
    sanitize_agent_name,
    walk_session,
)

# ---------------------------------------------------------------------------
# Local fixture builders (this repo's convention: each test file defines its
# own JSONL/meta builders rather than adding new fixtures to conftest.py).
# ---------------------------------------------------------------------------


def _write_meta(path: Path, agent_type: str) -> None:
    """Write a subagent ``*.meta.json`` file with the given ``agentType``.

    Args:
        path: Destination ``.meta.json`` path. Parent directory must exist.
        agent_type: Raw ``agentType`` value to embed.
    """
    path.write_text(json.dumps({"agentType": agent_type}), encoding="utf-8")


def _write_stub_jsonl(path: Path) -> None:
    """Write an empty JSONL transcript file.

    The walker never parses JSONL content — it only checks for existence —
    so an empty file is sufficient to represent "this agent's transcript
    exists".

    Args:
        path: Destination ``.jsonl`` path. Parent directory must exist.
    """
    path.write_text("", encoding="utf-8")


class TestSanitizeAgentName:
    def test_plain_name_passes_through(self) -> None:
        assert sanitize_agent_name("code-writer") == "code-writer"

    def test_separator_is_replaced(self, recwarn) -> None:
        assert sanitize_agent_name("a→b") == "a﹖b"
        assert len(recwarn) == 1


class TestWalkSession:
    def test_root_only_session_yields_one_transcript(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "sess-1.jsonl"
        jsonl.write_text("", encoding="utf-8")

        transcripts, subagent_types = walk_session(jsonl, "main")

        assert transcripts == [
            AgentTranscript(
                jsonl_path=jsonl,
                agent_type="main",
                agent_path=("main",),
            )
        ]
        assert subagent_types == []

    def test_nested_tree_yields_depth_first_preorder(
        self, nested_session_dir: Path
    ) -> None:
        jsonl = (
            nested_session_dir
            / "projects"
            / "C--Users-chris--myproject"
            / "sess-nested.jsonl"
        )

        transcripts, subagent_types = walk_session(jsonl, "general-purpose")

        assert [t.agent_path for t in transcripts] == [
            ("general-purpose",),
            ("general-purpose", "project-planner"),
            ("general-purpose", "project-planner", "Explore"),
        ]
        assert [t.agent_type for t in transcripts] == [
            "general-purpose",
            "project-planner",
            "Explore",
        ]
        assert subagent_types == ["project-planner", "Explore"]


class TestWalkSessionWorkflows:
    """Traversal of ``subagents/workflows/wf_<id>/`` directories (issue #253).

    When a session dispatches work via the ``Workflow()`` tool, individually
    ``agent()``-spawned sub-agents land as *siblings* directly inside one
    ``subagents/workflows/wf_<id>/`` directory — a different directory shape
    than the one-directory-per-agent ``subagents/<agent_id>/`` layout used
    for ordinary sub-agents. No synthetic "workflow" or "wf_<id>" path
    segment should appear in ``agent_path`` — the workflow itself is a
    script sandbox, not an addressable agent.
    """

    def test_workflow_dispatched_agents_are_yielded_as_root_siblings(
        self, tmp_path: Path
    ) -> None:
        """Two agents dispatched by one workflow appear as path siblings.

        ``subagents/workflows/wf_abc123/`` holds two agent-id pairs directly
        (no ``<agent_id>/`` subdirectory per pair). Both must be yielded
        with ``agent_path`` one level below the root — not nested under one
        another.
        """
        jsonl = tmp_path / "sess-wf1.jsonl"
        jsonl.write_text("", encoding="utf-8")
        wf_dir = tmp_path / "sess-wf1" / "subagents" / "workflows" / "wf_abc123"
        wf_dir.mkdir(parents=True)
        _write_meta(wf_dir / "agent-w1.meta.json", "code-writer")
        _write_stub_jsonl(wf_dir / "agent-w1.jsonl")
        _write_meta(wf_dir / "agent-w2.meta.json", "doc-writer")
        _write_stub_jsonl(wf_dir / "agent-w2.jsonl")

        transcripts, subagent_types = walk_session(jsonl, "main")

        agent_paths = {t.agent_path for t in transcripts}
        assert ("main", "code-writer") in agent_paths
        assert ("main", "doc-writer") in agent_paths
        # Siblings, not nested under each other.
        assert ("main", "code-writer", "doc-writer") not in agent_paths
        assert ("main", "doc-writer", "code-writer") not in agent_paths
        assert len(transcripts) == 3  # root + 2 workflow-dispatched agents
        # sorted(...), not set(...): duplicate-sensitive, catches an
        # over-broad glob (e.g. "**/*.meta.json") that would double-record
        # a type alongside the correct scoped scan.
        assert sorted(subagent_types) == ["code-writer", "doc-writer"]

    def test_ordinary_and_workflow_subagents_coexist_as_siblings(
        self, tmp_path: Path
    ) -> None:
        """An ordinary ``subagents/<id>/`` child and a workflow sibling both surface.

        Regression guard: the ordinary half of this tree should already pass
        today; the combined assertion set only goes fully green once the
        workflow half is also traversed.
        """
        jsonl = tmp_path / "sess-wf2.jsonl"
        jsonl.write_text("", encoding="utf-8")
        subagents_dir = tmp_path / "sess-wf2" / "subagents"
        subagents_dir.mkdir(parents=True)
        _write_meta(subagents_dir / "agent-ord.meta.json", "code-writer")
        _write_stub_jsonl(subagents_dir / "agent-ord.jsonl")

        wf_dir = subagents_dir / "workflows" / "wf_xyz"
        wf_dir.mkdir(parents=True)
        _write_meta(wf_dir / "agent-w1.meta.json", "doc-writer")
        _write_stub_jsonl(wf_dir / "agent-w1.jsonl")

        transcripts, subagent_types = walk_session(jsonl, "main")

        agent_paths = {t.agent_path for t in transcripts}
        assert ("main", "code-writer") in agent_paths
        assert ("main", "doc-writer") in agent_paths
        assert len(transcripts) == 3  # root + ordinary + workflow agent
        assert sorted(subagent_types) == ["code-writer", "doc-writer"]

    def test_workflow_nested_agent_recurses_into_its_own_subagents(
        self, tmp_path: Path
    ) -> None:
        """A workflow-dispatched agent's own descendants are still walked.

        ``agent-w1`` lives directly inside ``wf_abc/``, but it dispatched a
        further sub-agent at ``wf_abc/agent-w1/subagents/`` — the same
        one-directory-per-agent shape used for ordinary recursion. Full
        symmetry with the non-workflow case is expected.
        """
        jsonl = tmp_path / "sess-wf3.jsonl"
        jsonl.write_text("", encoding="utf-8")
        wf_dir = tmp_path / "sess-wf3" / "subagents" / "workflows" / "wf_abc"
        wf_dir.mkdir(parents=True)
        _write_meta(wf_dir / "agent-w1.meta.json", "code-writer")
        _write_stub_jsonl(wf_dir / "agent-w1.jsonl")

        grandchild_dir = wf_dir / "agent-w1" / "subagents"
        grandchild_dir.mkdir(parents=True)
        _write_meta(grandchild_dir / "agent-w1sub.meta.json", "Explore")
        _write_stub_jsonl(grandchild_dir / "agent-w1sub.jsonl")

        transcripts, subagent_types = walk_session(jsonl, "main")

        # Single-child-per-level chain: exact order is deterministic. This
        # also rules out an over-broad glob (e.g. "**/*.meta.json" instead
        # of the scoped "workflows/wf_*/*.meta.json" scan) that would
        # double-record "Explore" and emit a spurious extra transcript at
        # the wrong path ("main", "Explore").
        assert [t.agent_path for t in transcripts] == [
            ("main",),
            ("main", "code-writer"),
            ("main", "code-writer", "Explore"),
        ]
        assert sorted(subagent_types) == ["Explore", "code-writer"]

    def test_workflow_agent_missing_jsonl_recorded_in_types_not_yielded(
        self, tmp_path: Path
    ) -> None:
        """A ``.meta.json`` with no matching ``.jsonl`` under a workflow dir.

        Mirrors the existing rule for ordinary subagents (see
        ``_walk_subagents`` docstring: "Missing JSONL: silently skipped, but
        the type is still recorded"): no ``AgentTranscript`` is emitted, but
        the sanitized ``agentType`` still lands in ``subagent_types``.
        """
        jsonl = tmp_path / "sess-wf4.jsonl"
        jsonl.write_text("", encoding="utf-8")
        wf_dir = tmp_path / "sess-wf4" / "subagents" / "workflows" / "wf_missing"
        wf_dir.mkdir(parents=True)
        _write_meta(wf_dir / "agent-w1.meta.json", "code-writer")
        # Deliberately no agent-w1.jsonl.

        transcripts, subagent_types = walk_session(jsonl, "main")

        agent_paths = [t.agent_path for t in transcripts]
        assert ("main", "code-writer") not in agent_paths
        assert transcripts == [
            AgentTranscript(
                jsonl_path=jsonl,
                agent_type="main",
                agent_path=("main",),
            )
        ]
        assert subagent_types == ["code-writer"]

    def test_depth_cap_warning_fires_through_workflow_entry_point(
        self, tmp_path: Path
    ) -> None:
        """A chain entered via ``workflows/wf_*/`` still honors the depth cap.

        Depth 1 is a workflow-dispatched agent; depths 2-12 are ordinary
        nested subagents beneath it (12 levels total, two past
        ``MAX_AGENT_PATH_LENGTH`` = 10) — the same shared cap/warning
        machinery used for the ordinary-only case must fire here too,
        rather than infinite-looping or silently continuing past the cap.
        """
        jsonl = tmp_path / "sess-wf5.jsonl"
        jsonl.write_text("", encoding="utf-8")

        wf_dir = tmp_path / "sess-wf5" / "subagents" / "workflows" / "wf_deep"
        wf_dir.mkdir(parents=True)
        _write_meta(wf_dir / "agent-d01.meta.json", "depth-01")
        _write_stub_jsonl(wf_dir / "agent-d01.jsonl")

        current_parent = wf_dir / "agent-d01"
        for depth in range(2, 13):
            subagents_dir = current_parent / "subagents"
            subagents_dir.mkdir(parents=True)
            agent_id = f"agent-d{depth:02d}"
            _write_meta(subagents_dir / f"{agent_id}.meta.json", f"depth-{depth:02d}")
            _write_stub_jsonl(subagents_dir / f"{agent_id}.jsonl")
            current_parent = subagents_dir / agent_id

        with pytest.warns(UserWarning, match=r"path length cap"):
            transcripts, _ = walk_session(jsonl, "main")

        for t in transcripts:
            assert len(t.agent_path) <= 10, f"agent_path too long: {t.agent_path!r}"
