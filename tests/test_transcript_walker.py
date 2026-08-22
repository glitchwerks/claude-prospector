"""Tests for the shared transcript walker."""

from __future__ import annotations

from pathlib import Path

from claude_prospector.transcript_walker import (
    AgentTranscript,
    sanitize_agent_name,
    walk_session,
)


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
