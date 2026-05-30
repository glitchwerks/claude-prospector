"""Unit tests for issue #203 — project-name display improvements.

Tests cover:
- derive_project_name: cwd-first derivation with decode fallback.
- decode_project_hash_full: full-path reconstruction from slug.
- parse_sessions: cwd-first project name with full-path field.
- Config-driven exclude list: project filtering via config.json.

Regression fixture dir names (real samples):
- C--Users-chris-AppData-Local-Programs-Open-Design-release-stable-win-
  resources-app-prebundled
- C--Users-chris--claude
- i--games-skyrim-mods-oar-config-manager
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Tests for derive_project_name helper
# ---------------------------------------------------------------------------


class TestDeriveProjectName:
    """Tests for the shared derive_project_name helper in parser.py."""

    def test_cwd_first_returns_leaf(self) -> None:
        """When cwd is provided, returns Path(cwd).name."""
        from claude_prospector.parser import derive_project_name

        result = derive_project_name(
            cwd="I:/ai/claude/claude-prospector",
            slug_fallback="i--ai-claude-claude-prospector",
        )
        assert result == "claude-prospector"

    def test_cwd_none_falls_back_to_decode(self) -> None:
        """When cwd is None, falls back to decode_project_hash."""
        from claude_prospector.parser import derive_project_name

        result = derive_project_name(
            cwd=None,
            slug_fallback="C--Users-chris--claude",
        )
        assert result == "claude"

    def test_cwd_empty_string_falls_back_to_decode(self) -> None:
        """When cwd is empty string, falls back to decode_project_hash.

        ``i--games-skyrim-mods-oar-config-manager`` has one ``--``
        separator, so decode_project_hash returns the full segment after
        the drive letter (``games-skyrim-mods-oar-config-manager``).
        """
        from claude_prospector.parser import derive_project_name

        result = derive_project_name(
            cwd="",
            slug_fallback="i--games-skyrim-mods-oar-config-manager",
        )
        assert result == "games-skyrim-mods-oar-config-manager"

    def test_both_none_returns_unknown(self) -> None:
        """When both cwd and slug_fallback are absent, returns 'unknown'."""
        from claude_prospector.parser import derive_project_name

        result = derive_project_name(cwd=None, slug_fallback=None)
        assert result == "unknown"

    def test_cwd_windows_backslash_path(self) -> None:
        """Windows paths with backslashes resolve the correct leaf."""
        from claude_prospector.parser import derive_project_name

        result = derive_project_name(
            cwd="C:\\Users\\chris\\myproject",
            slug_fallback=None,
        )
        assert result == "myproject"

    def test_cwd_forward_slash_path(self) -> None:
        """Forward-slash paths resolve the correct leaf."""
        from claude_prospector.parser import derive_project_name

        result = derive_project_name(
            cwd="/home/user/myproject",
            slug_fallback=None,
        )
        assert result == "myproject"

    def test_slug_fallback_none_with_empty_decode_returns_unknown(
        self,
    ) -> None:
        """When slug_fallback decodes to '' (empty string), returns 'unknown'."""
        from claude_prospector.parser import derive_project_name

        # decode_project_hash("") returns "" — must fall through to "unknown"
        result = derive_project_name(cwd=None, slug_fallback="")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# Tests for decode_project_hash_full
# ---------------------------------------------------------------------------


class TestDecodeProjectHashFull:
    """Tests for decode_project_hash_full — full-path reconstruction."""

    def test_windows_drive_path(self) -> None:
        """C--Users-chris--claude decodes to C:/Users/chris/.claude."""
        from claude_prospector.parser import decode_project_hash_full

        # The slug encodes / as - and path-level transitions as --
        # C--Users-chris--claude → C:/Users/chris/.claude
        result = decode_project_hash_full("C--Users-chris--claude")
        assert "claude" in result
        # Must be a multi-segment path, not just the leaf
        assert len(result) > len("claude")

    def test_deep_open_design_path(self) -> None:
        """Real AppData slug decodes to a recognisable path.

        Regression fixture: the slug that caused the original bug — the
        leaf-only decode returned the entire tail after the drive as one
        unreadable blob.
        """
        from claude_prospector.parser import decode_project_hash_full

        slug = (
            "C--Users-chris-AppData-Local-Programs-Open-Design-"
            "release-stable-win-resources-app-prebundled"
        )
        result = decode_project_hash_full(slug)
        # Must contain multiple segments, not a single unreadable blob
        assert "prebundled" in result
        assert "Open" in result or "open" in result.lower()

    def test_i_drive_path(self) -> None:
        """i--games-skyrim-mods-oar-config-manager decodes correctly."""
        from claude_prospector.parser import decode_project_hash_full

        result = decode_project_hash_full("i--games-skyrim-mods-oar-config-manager")
        assert "games" in result
        assert "oar-config-manager" in result or "oar" in result

    def test_claude_prospector_root(self) -> None:
        """C--Users-chris--claude encodes a path with .claude in it."""
        from claude_prospector.parser import decode_project_hash_full

        result = decode_project_hash_full("C--Users-chris--claude")
        # Must produce a non-trivial path string
        assert result != "claude"

    def test_empty_slug_returns_empty(self) -> None:
        """Empty slug returns empty string."""
        from claude_prospector.parser import decode_project_hash_full

        assert decode_project_hash_full("") == ""

    def test_single_segment_no_separator(self) -> None:
        """Single-segment slug with no -- returns the segment unchanged."""
        from claude_prospector.parser import decode_project_hash_full

        assert decode_project_hash_full("myproject") == "myproject"


# ---------------------------------------------------------------------------
# Tests for SessionRecord.project_path field
# ---------------------------------------------------------------------------


class TestSessionRecordProjectPath:
    """Tests that parse_sessions populates the project_path field."""

    def _make_minimal_session(
        self,
        project_dir: Path,
        session_id: str,
        cwd: str | None = None,
    ) -> None:
        """Write a minimal session JSONL to project_dir."""
        lines: list[dict] = []
        if cwd is not None:
            lines.append(
                {
                    "type": "system",
                    "subtype": "init",
                    "cwd": cwd,
                    "timestamp": "2026-05-01T10:00:00.000Z",
                }
            )
        lines.append(
            {
                "type": "assistant",
                "timestamp": "2026-05-01T10:00:05.000Z",
                "sessionId": session_id,
                "message": {
                    "model": "claude-opus-4-6",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hi"}],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }
        )
        jsonl = project_dir / f"{session_id}.jsonl"
        jsonl.write_text(
            "\n".join(json.dumps(line) for line in lines),
            encoding="utf-8",
        )

    def test_session_has_project_path_field(self, tmp_path: Path) -> None:
        """SessionRecord exposes a project_path attribute."""
        from claude_prospector.parser import parse_sessions

        project_dir = tmp_path / "projects" / "C--Users-chris--claude"
        project_dir.mkdir(parents=True)
        self._make_minimal_session(
            project_dir, "sess-001", cwd="C:\\Users\\chris\\.claude"
        )

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1
        assert hasattr(sessions[0], "project_path")

    def test_project_path_is_full_path_when_cwd_available(self, tmp_path: Path) -> None:
        """When a cwd entry exists, project_path is the full cwd."""
        from claude_prospector.parser import parse_sessions

        cwd = "C:\\Users\\chris\\.claude"
        project_dir = tmp_path / "projects" / "C--Users-chris--claude"
        project_dir.mkdir(parents=True)
        self._make_minimal_session(project_dir, "sess-002", cwd=cwd)

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1
        assert sessions[0].project_path == cwd

    def test_project_path_fallback_is_decoded_slug(self, tmp_path: Path) -> None:
        """When no cwd entry, project_path is decode_project_hash_full(slug)."""
        from claude_prospector.parser import decode_project_hash_full, parse_sessions

        slug = "i--games-skyrim-mods-oar-config-manager"
        project_dir = tmp_path / "projects" / slug
        project_dir.mkdir(parents=True)
        # No cwd field
        self._make_minimal_session(project_dir, "sess-003", cwd=None)

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1
        expected_path = decode_project_hash_full(slug)
        assert sessions[0].project_path == expected_path

    def test_project_name_cwd_first(self, tmp_path: Path) -> None:
        """project field is the leaf of cwd, not decode_project_hash."""
        from claude_prospector.parser import parse_sessions

        # Slug decodes to 'claude', but cwd has '.claude' as leaf
        cwd = "C:\\Users\\chris\\.claude"
        slug = "C--Users-chris--claude"
        project_dir = tmp_path / "projects" / slug
        project_dir.mkdir(parents=True)
        self._make_minimal_session(project_dir, "sess-004", cwd=cwd)

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1
        assert sessions[0].project == ".claude"

    def test_project_name_fallback_to_decode(self, tmp_path: Path) -> None:
        """Without cwd, project falls back to decode_project_hash."""
        from claude_prospector.parser import parse_sessions

        slug = "C--Users-chris--claude"
        project_dir = tmp_path / "projects" / slug
        project_dir.mkdir(parents=True)
        self._make_minimal_session(project_dir, "sess-005", cwd=None)

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1
        # decode_project_hash('C--Users-chris--claude') == 'claude'
        assert sessions[0].project == "claude"


# ---------------------------------------------------------------------------
# Tests for config-driven exclude list
# ---------------------------------------------------------------------------


class TestProjectExcludeList:
    """Tests for the project-exclude config mechanism.

    The exclude list is read from config.json under the key
    ``project_exclude_patterns``. Each entry is a substring or glob
    that is matched against the full project_path.  Matching projects
    are hidden from parse_sessions output (omitted entirely).
    """

    def _make_session_with_cwd(
        self,
        project_dir: Path,
        session_id: str,
        cwd: str,
    ) -> None:
        """Write a minimal session with a cwd field."""
        lines = [
            {
                "type": "system",
                "subtype": "init",
                "cwd": cwd,
                "timestamp": "2026-05-01T10:00:00.000Z",
            },
            {
                "type": "assistant",
                "timestamp": "2026-05-01T10:00:05.000Z",
                "sessionId": session_id,
                "message": {
                    "model": "claude-opus-4-6",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hi"}],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ]
        jsonl = project_dir / f"{session_id}.jsonl"
        jsonl.write_text(
            "\n".join(json.dumps(line) for line in lines),
            encoding="utf-8",
        )

    def test_no_config_returns_all_sessions(self, tmp_path: Path) -> None:
        """Without a config file all sessions are returned."""
        from claude_prospector.parser import parse_sessions

        project_dir = tmp_path / "projects" / "some-project"
        project_dir.mkdir(parents=True)
        self._make_session_with_cwd(project_dir, "sess-a", "/home/user/myproject")

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1

    def test_exclude_pattern_hides_matching_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A matching exclude pattern removes the project from results.

        Regression fixture: Open Design Electron app dir.
        """
        from claude_prospector.parser import parse_sessions

        # Two projects: one real, one noise
        real_dir = tmp_path / "projects" / "C--Users-chris--claude-prospector"
        real_dir.mkdir(parents=True)
        self._make_session_with_cwd(
            real_dir, "sess-real", "C:\\Users\\chris\\claude-prospector"
        )

        noise_slug = (
            "C--Users-chris-AppData-Local-Programs-Open-Design-"
            "release-stable-win-resources-app-prebundled"
        )
        noise_dir = tmp_path / "projects" / noise_slug
        noise_dir.mkdir(parents=True)
        self._make_session_with_cwd(
            noise_dir,
            "sess-noise",
            "C:\\Users\\chris\\AppData\\Local\\Programs\\Open Design\\"
            "release\\stable\\win\\resources\\app\\prebundled",
        )

        # Write config with exclude pattern
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"project_exclude_patterns": ["AppData\\Local\\Programs"]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_PROSPECTOR_CONFIG", str(config_path))

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1
        assert sessions[0].session_id == "sess-real"

    def test_exclude_pattern_forward_slash_variant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Forward-slash pattern works for Unix-style paths."""
        from claude_prospector.parser import parse_sessions

        noise_dir = tmp_path / "projects" / "some-electron-slug"
        noise_dir.mkdir(parents=True)
        self._make_session_with_cwd(
            noise_dir,
            "sess-electron",
            "/home/user/.local/share/ElectronApp/resources/app",
        )

        real_dir = tmp_path / "projects" / "my-project"
        real_dir.mkdir(parents=True)
        self._make_session_with_cwd(real_dir, "sess-good", "/home/user/my-project")

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"project_exclude_patterns": ["ElectronApp/resources"]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_PROSPECTOR_CONFIG", str(config_path))

        sessions = parse_sessions(tmp_path)
        project_names = {s.project for s in sessions}
        assert "my-project" in project_names
        assert "app" not in project_names

    def test_exclude_empty_list_returns_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty exclude list returns all projects."""
        from claude_prospector.parser import parse_sessions

        project_dir = tmp_path / "projects" / "good-project"
        project_dir.mkdir(parents=True)
        self._make_session_with_cwd(project_dir, "sess-good", "/home/user/good-project")

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"project_exclude_patterns": []}),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_PROSPECTOR_CONFIG", str(config_path))

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1

    def test_exclude_warp_worktrees_pattern(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Warp worktrees pattern hides Warp noise sessions.

        Regression fixture: warp-Warp-data-worktrees-... directory.
        """
        from claude_prospector.parser import parse_sessions

        warp_dir = (
            tmp_path / "projects" / "C--Users-chris-warp-Warp-data-worktrees-uuid"
        )
        warp_dir.mkdir(parents=True)
        self._make_session_with_cwd(
            warp_dir,
            "sess-warp",
            "C:\\Users\\chris\\warp\\Warp\\data\\worktrees\\some-uuid",
        )

        real_dir = tmp_path / "projects" / "C--Users-chris--myproject"
        real_dir.mkdir(parents=True)
        self._make_session_with_cwd(
            real_dir, "sess-real", "C:\\Users\\chris\\myproject"
        )

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"project_exclude_patterns": ["warp\\Warp\\data\\worktrees"]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_PROSPECTOR_CONFIG", str(config_path))

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1
        assert sessions[0].session_id == "sess-real"

    def test_malformed_config_does_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Malformed config.json is silently ignored; all sessions returned."""
        from claude_prospector.parser import parse_sessions

        project_dir = tmp_path / "projects" / "project-a"
        project_dir.mkdir(parents=True)
        self._make_session_with_cwd(project_dir, "sess-a", "/home/user/project-a")

        config_path = tmp_path / "config.json"
        config_path.write_text("this is not json", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROSPECTOR_CONFIG", str(config_path))

        sessions = parse_sessions(tmp_path)
        assert len(sessions) == 1


# ---------------------------------------------------------------------------
# Tests for by_project full_path in aggregator output
# ---------------------------------------------------------------------------


class TestAggregatorProjectPath:
    """Tests that aggregator carries project_path into by_project."""

    def _make_session_record(
        self,
        project: str,
        project_path: str,
        session_id: str,
    ) -> object:
        """Build a minimal SessionRecord for aggregation tests."""
        from datetime import datetime, timezone

        from claude_prospector.models import MessageRecord, SessionRecord

        msg = MessageRecord(
            timestamp=datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
            model="claude-opus-4-6",
            agent_type="main",
            skill=None,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            agent_path=("main",),
        )
        return SessionRecord(
            session_id=session_id,
            project=project,
            project_path=project_path,
            start_time=datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
            root_agent="main",
            messages=[msg],
            subagent_types=[],
        )

    def test_by_project_contains_full_path(self) -> None:
        """AggregateResult.by_project[name]['full_path'] is project_path."""
        from claude_prospector.aggregator import aggregate

        sessions = [
            self._make_session_record(
                "claude-prospector",
                "C:\\Users\\chris\\claude-prospector",
                "sess-agg-01",
            )
        ]
        result = aggregate(sessions)
        assert "claude-prospector" in result.by_project
        assert (
            result.by_project["claude-prospector"]["full_path"]
            == "C:\\Users\\chris\\claude-prospector"
        )

    def test_by_project_full_path_uses_first_seen(self) -> None:
        """When multiple sessions share a project name, first full_path wins."""
        from claude_prospector.aggregator import aggregate

        sessions = [
            self._make_session_record(
                "myproj",
                "/home/user/myproj",
                "sess-agg-02a",
            ),
            self._make_session_record(
                "myproj",
                "/home/user/myproj",
                "sess-agg-02b",
            ),
        ]
        result = aggregate(sessions)
        assert result.by_project["myproj"]["full_path"] == "/home/user/myproj"


# ---------------------------------------------------------------------------
# Tests for regression fixtures — decode behavior on real slug names
# ---------------------------------------------------------------------------


class TestRealSlugRegression:
    """Regression tests using real directory names from the issue."""

    @pytest.mark.parametrize(
        "slug, expected_leaf",
        [
            # C--Users-chris--claude has TWO '--' separators:
            # segments = ['C', 'Users-chris', 'claude'] → last = 'claude'
            (
                "C--Users-chris--claude",
                "claude",
            ),
            # i--games-skyrim-mods-oar-config-manager has ONE '--' separator:
            # segments = ['i', 'games-skyrim-mods-oar-config-manager']
            # → last = 'games-skyrim-mods-oar-config-manager'
            # (The full tail, which is the problem this issue fixes via cwd-first)
            (
                "i--games-skyrim-mods-oar-config-manager",
                "games-skyrim-mods-oar-config-manager",
            ),
            # Open Design slug has ONE '--' separator (C--<huge-tail>):
            # segments = ['C', 'Users-chris-AppData-...-prebundled']
            # → last = 'Users-chris-AppData-...-prebundled'
            # (This is the regression case — the full tail is unreadable)
            (
                "C--Users-chris-AppData-Local-Programs-Open-Design-"
                "release-stable-win-resources-app-prebundled",
                "Users-chris-AppData-Local-Programs-Open-Design-"
                "release-stable-win-resources-app-prebundled",
            ),
        ],
    )
    def test_decode_project_hash_leaf(self, slug: str, expected_leaf: str) -> None:
        """decode_project_hash returns the last '--'-separated segment.

        For slugs with only one '--' the last segment IS the full tail
        after the drive letter — which is the readability problem that
        the cwd-first strategy in derive_project_name fixes.
        """
        from claude_prospector.parser import decode_project_hash

        assert decode_project_hash(slug) == expected_leaf

    @pytest.mark.parametrize(
        "slug",
        [
            "C--Users-chris-AppData-Local-Programs-Open-Design-"
            "release-stable-win-resources-app-prebundled",
            "C--Users-chris--claude",
            "i--games-skyrim-mods-oar-config-manager",
        ],
    )
    def test_decode_project_hash_full_longer_than_leaf(self, slug: str) -> None:
        """Full decode always returns more than just the leaf segment."""
        from claude_prospector.parser import (
            decode_project_hash,
            decode_project_hash_full,
        )

        leaf = decode_project_hash(slug)
        full = decode_project_hash_full(slug)
        # For multi-segment slugs, full path must be longer than the leaf
        if "--" in slug:
            assert len(full) > len(leaf), (
                f"Full path '{full}' should be longer than leaf '{leaf}' "
                f"for slug '{slug}'"
            )
