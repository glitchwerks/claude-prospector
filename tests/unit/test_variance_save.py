"""Tests for variance-save subcommand and the session-id resolver.

Covers:
- combine logic: 1a audit data + judgment fields → combined schema
- session-id → path resolution (found / not-found / ambiguous-multiple)
- judgment read from file and from stdin
- malformed judgment JSON
- missing required judgment keys (variance, not_done)
- severity optional (defaults to null)
- idempotent overwrite (re-run for same session-id overwrites)
- variance/ dir created automatically
- session-audit --session-id resolution path (CLI integration)
- decoupled roots: transcript search root (~/.claude) vs output root (base_dir())
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _user_line(
    text: str,
    user_type: str = "external",
    session_id: str = "test-session",
) -> dict:
    """Build a minimal user message dict for JSONL fixtures.

    Args:
        text: Plain-text message content.
        user_type: The ``userType`` field.
        session_id: The session identifier string.

    Returns:
        A dict shaped like a real Claude Code JSONL user entry.
    """
    return {
        "type": "user",
        "userType": user_type,
        "sessionId": session_id,
        "message": {
            "role": "user",
            "content": text,
        },
    }


def _assistant_with_edit(
    tool_name: str,
    file_path: str,
    session_id: str = "test-session",
) -> dict:
    """Build an assistant message containing a single edit tool_use block.

    Args:
        tool_name: e.g. ``"Edit"``, ``"Write"``, ``"NotebookEdit"``.
        file_path: Target file path for the tool_use.
        session_id: The session identifier string.

    Returns:
        A dict shaped like a real Claude Code JSONL assistant entry.
    """
    return {
        "type": "assistant",
        "sessionId": session_id,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu-1",
                    "name": tool_name,
                    "input": {"file_path": file_path},
                }
            ],
        },
    }


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    """Write a list of dicts as JSONL to *path*.

    Args:
        path: Destination file path.
        lines: Dicts to serialise, one per line.
    """
    path.write_text(
        "\n".join(json.dumps(line) for line in lines),
        encoding="utf-8",
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    """Run claude_prospector as a module and capture raw output bytes.

    Args:
        *args: CLI arguments appended after the module name.

    Returns:
        CompletedProcess with stdout/stderr as bytes and returncode.
    """
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", *args],
        capture_output=True,
    )


def _run_cli_with_stdin(
    stdin_data: bytes,
    *args: str,
) -> subprocess.CompletedProcess[bytes]:
    """Run claude_prospector with bytes piped to stdin.

    Args:
        stdin_data: Bytes to pipe to the process stdin.
        *args: CLI arguments appended after the module name.

    Returns:
        CompletedProcess with stdout/stderr as bytes and returncode.
    """
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", *args],
        input=stdin_data,
        capture_output=True,
    )


def _import_variance_save():
    """Import variance_save module; raise ImportError if absent."""
    from claude_prospector.cli import variance_save  # noqa: PLC0415

    return variance_save


def _import_session_audit():
    """Import session_audit module; raise ImportError if absent."""
    from claude_prospector.cli import session_audit  # noqa: PLC0415

    return session_audit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def claude_data_dir(tmp_path: Path) -> Path:
    """Create a minimal ~/.claude-like data directory layout.

    Returns:
        The root data directory (the ``tmp_path``).
    """
    (tmp_path / "projects").mkdir()
    return tmp_path


@pytest.fixture()
def transcript_in_data_dir(
    claude_data_dir: Path,
) -> tuple[Path, str]:
    """Place a single-session transcript under projects/.

    Creates ``projects/my-project/<session-id>.jsonl`` containing one
    user ask and one Edit action.

    Returns:
        Tuple of ``(data_dir, session_id)``.
    """
    session_id = "abc-session-001"
    project_dir = claude_data_dir / "projects" / "C--some-project"
    project_dir.mkdir(parents=True)
    transcript = project_dir / f"{session_id}.jsonl"
    _write_jsonl(
        transcript,
        [
            _user_line("Implement the feature.", session_id=session_id),
            _assistant_with_edit("Edit", "src/feature.py", session_id=session_id),
        ],
    )
    return claude_data_dir, session_id


@pytest.fixture()
def good_judgment() -> dict:
    """Return a minimal valid judgment dict."""
    return {
        "variance": "Added extra logging that was not requested.",
        "not_done": "Tests were not written.",
        "severity": 2,
    }


# ===========================================================================
# TestVarianceSaveImport — module contract
# ===========================================================================


class TestVarianceSaveImport:
    """variance_save module must exist and export the required symbols."""

    def test_module_importable(self) -> None:
        """variance_save module must be importable from the cli package."""
        mod = _import_variance_save()
        assert mod is not None

    def test_build_parser_callable(self) -> None:
        """variance_save must export a build_parser callable."""
        mod = _import_variance_save()
        assert callable(mod.build_parser)

    def test_run_callable(self) -> None:
        """variance_save must export a run callable."""
        mod = _import_variance_save()
        assert callable(mod.run)

    def test_combine_variance_callable(self) -> None:
        """variance_save must export a combine_variance pure function."""
        mod = _import_variance_save()
        assert callable(mod.combine_variance)


# ===========================================================================
# TestSessionIdResolver — resolve_session_id_to_path
# ===========================================================================


class TestSessionIdResolver:
    """resolve_session_id_to_path must correctly map a session-id to a Path."""

    def test_found_returns_path(
        self,
        transcript_in_data_dir: tuple[Path, str],
    ) -> None:
        """A known session-id resolves to the transcript path."""
        data_dir, session_id = transcript_in_data_dir
        mod = _import_variance_save()
        result = mod.resolve_session_id_to_path(session_id, data_dir)
        assert result.exists()
        assert result.name == f"{session_id}.jsonl"

    def test_not_found_raises_file_not_found(
        self,
        claude_data_dir: Path,
    ) -> None:
        """An unknown session-id raises FileNotFoundError."""
        mod = _import_variance_save()
        with pytest.raises(FileNotFoundError, match="no-such-id"):
            mod.resolve_session_id_to_path("no-such-id", claude_data_dir)

    def test_ambiguous_raises_value_error(
        self,
        claude_data_dir: Path,
    ) -> None:
        """Multiple matches for the same session-id raise ValueError."""
        session_id = "duplicate-session"
        # Place two transcripts with the same name in different projects
        for proj in ("proj-a", "proj-b"):
            d = claude_data_dir / "projects" / proj
            d.mkdir(parents=True)
            _write_jsonl(d / f"{session_id}.jsonl", [])
        mod = _import_variance_save()
        with pytest.raises(ValueError, match="duplicate-session"):
            mod.resolve_session_id_to_path(session_id, claude_data_dir)

    def test_error_message_names_the_session_id(
        self,
        claude_data_dir: Path,
    ) -> None:
        """FileNotFoundError message must include the session-id."""
        session_id = "missing-xyz-999"
        mod = _import_variance_save()
        with pytest.raises(FileNotFoundError) as exc_info:
            mod.resolve_session_id_to_path(session_id, claude_data_dir)
        assert "missing-xyz-999" in str(exc_info.value)


# ===========================================================================
# TestSessionAuditSessionIdArg — --session-id on session-audit CLI
# ===========================================================================


class TestSessionAuditSessionIdArg:
    """session-audit must accept --session-id as an alternative to --path."""

    def test_session_id_resolves_and_exits_0(
        self,
        transcript_in_data_dir: tuple[Path, str],
    ) -> None:
        """--session-id resolving a known transcript exits 0 with JSON."""
        data_dir, session_id = transcript_in_data_dir
        import os

        env = {**os.environ, "CLAUDE_PROSPECTOR_BASE_DIR": str(data_dir)}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "session-audit",
                "--session-id",
                session_id,
                "--data-dir",
                str(data_dir),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode == 0
        parsed = json.loads(result.stdout.decode("utf-8"))
        assert parsed["original_ask"] == "Implement the feature."

    def test_session_id_not_found_exits_nonzero(
        self,
        claude_data_dir: Path,
    ) -> None:
        """--session-id for a missing session exits non-zero."""
        import os

        env = {**os.environ, "CLAUDE_PROSPECTOR_BASE_DIR": str(claude_data_dir)}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "session-audit",
                "--session-id",
                "nonexistent-session-abc",
                "--data-dir",
                str(claude_data_dir),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode != 0

    def test_path_and_session_id_mutually_exclusive(
        self,
        tmp_path: Path,
    ) -> None:
        """Passing both --path and --session-id must exit non-zero."""
        f = tmp_path / "x.jsonl"
        _write_jsonl(f, [])
        result = _run_cli(
            "session-audit",
            "--path",
            str(f),
            "--session-id",
            "some-id",
        )
        assert result.returncode != 0

    def test_neither_path_nor_session_id_exits_nonzero(self) -> None:
        """Passing neither --path nor --session-id must exit non-zero."""
        result = _run_cli("session-audit")
        assert result.returncode != 0


# ===========================================================================
# TestCombineVariance — pure function combine_variance()
# ===========================================================================


class TestCombineVariance:
    """combine_variance merges 1a audit data with judgment into full schema."""

    def test_combined_schema_has_all_keys(
        self,
        good_judgment: dict,
    ) -> None:
        """combine_variance output has all required combined-schema keys.

        Phase 0: schema now includes 'timestamp'.
        """
        mod = _import_variance_save()
        audit = {
            "original_ask": "Do the thing.",
            "prior_asks": [],
            "actions": [],
        }
        result = mod.combine_variance("my-session-id", audit, good_judgment)
        required = {
            "session_id",
            "original_ask",
            "prior_asks",
            "actions",
            "variance",
            "not_done",
            "severity",
            "timestamp",
        }
        assert required == set(result.keys())

    def test_timestamp_default_is_none(
        self,
        good_judgment: dict,
    ) -> None:
        """timestamp defaults to None when not passed to combine_variance."""
        mod = _import_variance_save()
        audit = {"original_ask": None, "prior_asks": [], "actions": []}
        result = mod.combine_variance("s-ts-default", audit, good_judgment)
        assert result["timestamp"] is None

    def test_timestamp_populated_when_passed(
        self,
        good_judgment: dict,
    ) -> None:
        """timestamp field is preserved when a value is passed explicitly."""
        mod = _import_variance_save()
        audit = {"original_ask": None, "prior_asks": [], "actions": []}
        ts = "2026-01-15T10:30:00+00:00"
        result = mod.combine_variance("s-ts-value", audit, good_judgment, timestamp=ts)
        assert result["timestamp"] == ts

    def test_session_id_in_output(
        self,
        good_judgment: dict,
    ) -> None:
        """session_id field in output equals the passed session-id."""
        mod = _import_variance_save()
        audit = {"original_ask": None, "prior_asks": [], "actions": []}
        result = mod.combine_variance("sess-xyz", audit, good_judgment)
        assert result["session_id"] == "sess-xyz"

    def test_audit_fields_preserved(
        self,
        good_judgment: dict,
    ) -> None:
        """Audit fields (original_ask, prior_asks, actions) are preserved."""
        mod = _import_variance_save()
        audit = {
            "original_ask": "Build the widget.",
            "prior_asks": ["also do tests"],
            "actions": [{"tool": "Edit", "file_path": "src/widget.py"}],
        }
        result = mod.combine_variance("sid", audit, good_judgment)
        assert result["original_ask"] == "Build the widget."
        assert result["prior_asks"] == ["also do tests"]
        assert result["actions"] == [{"tool": "Edit", "file_path": "src/widget.py"}]

    def test_judgment_fields_merged(self) -> None:
        """Judgment fields (variance, not_done, severity) are merged."""
        mod = _import_variance_save()
        audit = {"original_ask": None, "prior_asks": [], "actions": []}
        judgment = {
            "variance": "Wrote extra docs.",
            "not_done": "Tests skipped.",
            "severity": 3,
        }
        result = mod.combine_variance("s1", audit, judgment)
        assert result["variance"] == "Wrote extra docs."
        assert result["not_done"] == "Tests skipped."
        assert result["severity"] == 3

    def test_severity_defaults_to_null_when_absent(self) -> None:
        """severity defaults to None when not present in judgment."""
        mod = _import_variance_save()
        audit = {"original_ask": None, "prior_asks": [], "actions": []}
        judgment = {"variance": "v", "not_done": "nd"}
        result = mod.combine_variance("s2", audit, judgment)
        assert result["severity"] is None

    def test_severity_null_when_explicitly_null(self) -> None:
        """severity=null in judgment becomes None in combined output."""
        mod = _import_variance_save()
        audit = {"original_ask": None, "prior_asks": [], "actions": []}
        judgment = {"variance": "v", "not_done": "nd", "severity": None}
        result = mod.combine_variance("s3", audit, judgment)
        assert result["severity"] is None


# ===========================================================================
# TestJudgmentValidation — validate_judgment()
# ===========================================================================


class TestJudgmentValidation:
    """validate_judgment must reject malformed or incomplete input."""

    def test_valid_judgment_passes(self, good_judgment: dict) -> None:
        """A complete judgment dict must not raise."""
        mod = _import_variance_save()
        mod.validate_judgment(good_judgment)  # must not raise

    def test_missing_variance_raises_value_error(self) -> None:
        """Missing 'variance' key raises ValueError."""
        mod = _import_variance_save()
        with pytest.raises(ValueError, match="variance"):
            mod.validate_judgment({"not_done": "nd"})

    def test_missing_not_done_raises_value_error(self) -> None:
        """Missing 'not_done' key raises ValueError."""
        mod = _import_variance_save()
        with pytest.raises(ValueError, match="not_done"):
            mod.validate_judgment({"variance": "v"})

    def test_both_missing_raises_value_error(self) -> None:
        """Both keys missing raises ValueError."""
        mod = _import_variance_save()
        with pytest.raises(ValueError):
            mod.validate_judgment({"severity": 1})

    def test_extra_keys_do_not_raise(self) -> None:
        """Extra keys beyond the required set must not cause errors."""
        mod = _import_variance_save()
        mod.validate_judgment(
            {"variance": "v", "not_done": "nd", "severity": 1, "extra": "ok"}
        )


# ===========================================================================
# TestVarianceSaveIntegration — save_variance_record() I/O
# ===========================================================================


class TestVarianceSaveIntegration:
    """save_variance_record writes the combined JSON to the variance dir."""

    def test_writes_to_variance_subdir(
        self,
        transcript_in_data_dir: tuple[Path, str],
        good_judgment: dict,
    ) -> None:
        """Record is written to <out_base_dir>/variance/<session_id>.json."""
        data_dir, session_id = transcript_in_data_dir
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=good_judgment,
            out_base_dir=data_dir,
        )
        expected = data_dir / "variance" / f"{session_id}.json"
        assert out_path == expected
        assert out_path.exists()

    def test_written_json_is_valid(
        self,
        transcript_in_data_dir: tuple[Path, str],
        good_judgment: dict,
    ) -> None:
        """The written file must be valid JSON matching the combined schema."""
        data_dir, session_id = transcript_in_data_dir
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=good_judgment,
            out_base_dir=data_dir,
        )
        with open(out_path, encoding="utf-8") as fh:
            record = json.load(fh)
        required = {
            "session_id",
            "original_ask",
            "prior_asks",
            "actions",
            "variance",
            "not_done",
            "severity",
            "timestamp",
        }
        assert required == set(record.keys())
        assert record["session_id"] == session_id
        assert record["original_ask"] == "Implement the feature."
        assert record["actions"][0]["file_path"] == "src/feature.py"

    def test_variance_dir_created_if_absent(
        self,
        transcript_in_data_dir: tuple[Path, str],
        good_judgment: dict,
    ) -> None:
        """variance/ directory is created automatically if it doesn't exist."""
        data_dir, session_id = transcript_in_data_dir
        variance_dir = data_dir / "variance"
        assert not variance_dir.exists()
        mod = _import_variance_save()
        mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=good_judgment,
            out_base_dir=data_dir,
        )
        assert variance_dir.is_dir()

    def test_idempotent_overwrite(
        self,
        transcript_in_data_dir: tuple[Path, str],
    ) -> None:
        """Running twice for the same session-id overwrites the first record."""
        data_dir, session_id = transcript_in_data_dir
        mod = _import_variance_save()
        first_judgment = {
            "variance": "First variance.",
            "not_done": "First not done.",
            "severity": 1,
        }
        second_judgment = {
            "variance": "Second variance.",
            "not_done": "Second not done.",
            "severity": 5,
        }
        mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=first_judgment,
            out_base_dir=data_dir,
        )
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=second_judgment,
            out_base_dir=data_dir,
        )
        with open(out_path, encoding="utf-8") as fh:
            record = json.load(fh)
        assert record["variance"] == "Second variance."
        assert record["severity"] == 5

    def test_explicit_out_override(
        self,
        transcript_in_data_dir: tuple[Path, str],
        good_judgment: dict,
        tmp_path: Path,
    ) -> None:
        """--out override directs the JSON file to an explicit path."""
        data_dir, session_id = transcript_in_data_dir
        explicit_out = tmp_path / "custom_output.json"
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=good_judgment,
            out_path=explicit_out,
        )
        assert out_path == explicit_out
        assert explicit_out.exists()


# ===========================================================================
# TestVarianceSaveCLI — subprocess integration via run()
# ===========================================================================


class TestVarianceSaveCLI:
    """variance-save subcommand must be wired and functional end-to-end."""

    def test_variance_save_in_help_output(self) -> None:
        """'python -m claude_prospector' help must list 'variance-save'."""
        result = _run_cli()
        combined = result.stdout.decode(
            "utf-8", errors="replace"
        ) + result.stderr.decode("utf-8", errors="replace")
        assert "variance-save" in combined

    def test_variance_save_help_exits_0(self) -> None:
        """'variance-save --help' must exit 0."""
        result = _run_cli("variance-save", "--help")
        assert result.returncode == 0

    def test_judgment_from_file_writes_record(
        self,
        transcript_in_data_dir: tuple[Path, str],
        good_judgment: dict,
        tmp_path: Path,
    ) -> None:
        """--judgment-file reads judgment JSON and writes the record."""
        data_dir, session_id = transcript_in_data_dir
        judgment_file = tmp_path / "judgment.json"
        judgment_file.write_text(json.dumps(good_judgment), encoding="utf-8")
        out_path = tmp_path / "output.json"
        import os

        env = {**os.environ, "CLAUDE_PROSPECTOR_BASE_DIR": str(data_dir)}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "variance-save",
                "--session-id",
                session_id,
                "--judgment-file",
                str(judgment_file),
                "--data-dir",
                str(data_dir),
                "--out",
                str(out_path),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode == 0
        assert out_path.exists()
        written_path = result.stdout.decode("utf-8").strip()
        assert written_path  # must print path to stdout

    def test_judgment_from_stdin_writes_record(
        self,
        transcript_in_data_dir: tuple[Path, str],
        good_judgment: dict,
        tmp_path: Path,
    ) -> None:
        """Judgment JSON piped to stdin writes the record."""
        data_dir, session_id = transcript_in_data_dir
        out_path = tmp_path / "output_stdin.json"
        stdin_bytes = json.dumps(good_judgment).encode("utf-8")
        import os

        env = {**os.environ, "CLAUDE_PROSPECTOR_BASE_DIR": str(data_dir)}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "variance-save",
                "--session-id",
                session_id,
                "--data-dir",
                str(data_dir),
                "--out",
                str(out_path),
            ],
            input=stdin_bytes,
            capture_output=True,
            env=env,
        )
        assert result.returncode == 0
        assert out_path.exists()

    def test_malformed_judgment_json_exits_nonzero(
        self,
        transcript_in_data_dir: tuple[Path, str],
        tmp_path: Path,
    ) -> None:
        """Malformed judgment JSON exits non-zero."""
        data_dir, session_id = transcript_in_data_dir
        judgment_file = tmp_path / "bad.json"
        judgment_file.write_text("}{not json", encoding="utf-8")
        import os

        env = {**os.environ, "CLAUDE_PROSPECTOR_BASE_DIR": str(data_dir)}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "variance-save",
                "--session-id",
                session_id,
                "--judgment-file",
                str(judgment_file),
                "--data-dir",
                str(data_dir),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode != 0

    def test_missing_variance_key_exits_nonzero(
        self,
        transcript_in_data_dir: tuple[Path, str],
        tmp_path: Path,
    ) -> None:
        """Judgment missing 'variance' key exits non-zero."""
        data_dir, session_id = transcript_in_data_dir
        judgment_file = tmp_path / "missing_variance.json"
        judgment_file.write_text(json.dumps({"not_done": "nd"}), encoding="utf-8")
        import os

        env = {**os.environ, "CLAUDE_PROSPECTOR_BASE_DIR": str(data_dir)}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "variance-save",
                "--session-id",
                session_id,
                "--judgment-file",
                str(judgment_file),
                "--data-dir",
                str(data_dir),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode != 0

    def test_missing_not_done_key_exits_nonzero(
        self,
        transcript_in_data_dir: tuple[Path, str],
        tmp_path: Path,
    ) -> None:
        """Judgment missing 'not_done' key exits non-zero."""
        data_dir, session_id = transcript_in_data_dir
        judgment_file = tmp_path / "missing_not_done.json"
        judgment_file.write_text(json.dumps({"variance": "v"}), encoding="utf-8")
        import os

        env = {**os.environ, "CLAUDE_PROSPECTOR_BASE_DIR": str(data_dir)}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "variance-save",
                "--session-id",
                session_id,
                "--judgment-file",
                str(judgment_file),
                "--data-dir",
                str(data_dir),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode != 0

    def test_unknown_session_id_exits_nonzero(
        self,
        claude_data_dir: Path,
        good_judgment: dict,
        tmp_path: Path,
    ) -> None:
        """Unknown session-id passed to variance-save exits non-zero."""
        judgment_file = tmp_path / "j.json"
        judgment_file.write_text(json.dumps(good_judgment), encoding="utf-8")
        import os

        env = {
            **os.environ,
            "CLAUDE_PROSPECTOR_BASE_DIR": str(claude_data_dir),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "variance-save",
                "--session-id",
                "no-such-session-xyz",
                "--judgment-file",
                str(judgment_file),
                "--data-dir",
                str(claude_data_dir),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode != 0

    def test_output_path_printed_to_stdout(
        self,
        transcript_in_data_dir: tuple[Path, str],
        good_judgment: dict,
        tmp_path: Path,
    ) -> None:
        """Written path is printed to stdout on success."""
        data_dir, session_id = transcript_in_data_dir
        judgment_file = tmp_path / "j.json"
        judgment_file.write_text(json.dumps(good_judgment), encoding="utf-8")
        out_path = tmp_path / "result.json"
        import os

        env = {**os.environ, "CLAUDE_PROSPECTOR_BASE_DIR": str(data_dir)}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "variance-save",
                "--session-id",
                session_id,
                "--judgment-file",
                str(judgment_file),
                "--data-dir",
                str(data_dir),
                "--out",
                str(out_path),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode == 0
        stdout = result.stdout.decode("utf-8").strip()
        assert str(out_path) in stdout or out_path.name in stdout


# ===========================================================================
# TestDecoupledRoots — transcript root vs output root are independent
# ===========================================================================


class TestDecoupledRoots:
    """Transcript search root and variance output root must be independent.

    The dual-root footgun: before this fix --data-dir was used for BOTH
    locating transcripts (needs ~/.claude) AND placing output files
    (needs base_dir()).  After the fix the two are decoupled:

    - ``--data-dir`` defaults to ``~/.claude`` — used only for
      transcript search (``projects/<id>.jsonl``).
    - Output defaults to ``base_dir()/variance/<session_id>.json``
      independently, controlled by ``CLAUDE_PROSPECTOR_BASE_DIR``.
    """

    @pytest.fixture()
    def two_root_setup(self, tmp_path: Path) -> tuple[Path, Path, str]:
        """Create two *distinct* temp directories: claude_data and base_dir.

        claude_data mirrors the ~/.claude layout with a transcript.
        base_dir is the plugin-data output root (distinct from claude_data).

        Returns:
            Tuple of (claude_data_dir, out_base_dir, session_id).
        """
        claude_data = tmp_path / "fake_claude_home"
        out_base = tmp_path / "fake_plugin_data"
        session_id = "split-roots-session-001"

        # Set up a transcript under the claude_data root.
        project_dir = claude_data / "projects" / "C--my-project"
        project_dir.mkdir(parents=True)
        transcript = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            transcript,
            [
                _user_line("Build the widget.", session_id=session_id),
                _assistant_with_edit("Edit", "src/widget.py", session_id=session_id),
            ],
        )
        out_base.mkdir(parents=True)
        return claude_data, out_base, session_id

    def test_transcript_found_in_claude_data_dir(
        self,
        two_root_setup: tuple[Path, Path, str],
        good_judgment: dict,
    ) -> None:
        """save_variance_record reads transcript from data_dir (not out_base_dir)."""
        claude_data, out_base, session_id = two_root_setup
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=claude_data,
            judgment=good_judgment,
            out_base_dir=out_base,
        )
        # Output must exist and contain the transcript's content.
        assert out_path.exists()
        with open(out_path, encoding="utf-8") as fh:
            record = json.load(fh)
        assert record["original_ask"] == "Build the widget."

    def test_output_lands_under_out_base_dir_not_data_dir(
        self,
        two_root_setup: tuple[Path, Path, str],
        good_judgment: dict,
    ) -> None:
        """Default output path is <out_base_dir>/variance/<id>.json, NOT under data_dir."""
        claude_data, out_base, session_id = two_root_setup
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=claude_data,
            judgment=good_judgment,
            out_base_dir=out_base,
        )
        # Must be under out_base, NOT under claude_data.
        assert out_path.is_relative_to(
            out_base
        ), f"Output {out_path} should be under out_base {out_base}"
        assert not out_path.is_relative_to(
            claude_data
        ), f"Output {out_path} must NOT be under claude_data {claude_data}"
        assert out_path == out_base / "variance" / f"{session_id}.json"

    def test_roots_are_genuinely_different_directories(
        self,
        two_root_setup: tuple[Path, Path, str],
    ) -> None:
        """The two root directories in two_root_setup are distinct paths."""
        claude_data, out_base, _session_id = two_root_setup
        assert claude_data != out_base
        # Neither is a parent of the other.
        assert not out_base.is_relative_to(claude_data)
        assert not claude_data.is_relative_to(out_base)

    def test_cli_default_paths_use_separate_roots(
        self,
        two_root_setup: tuple[Path, Path, str],
        good_judgment: dict,
        tmp_path: Path,
    ) -> None:
        """CLI with no --out uses base_dir() for output while --data-dir is ~/.claude.

        Uses CLAUDE_PROSPECTOR_BASE_DIR to redirect base_dir() to out_base,
        and --data-dir to redirect transcript search to claude_data.
        The two roots point at distinct directories; the output file must
        land under out_base, not under claude_data.
        """
        import os

        claude_data, out_base, session_id = two_root_setup
        judgment_file = tmp_path / "j.json"
        judgment_file.write_text(json.dumps(good_judgment), encoding="utf-8")

        env = {
            **os.environ,
            "CLAUDE_PROSPECTOR_BASE_DIR": str(out_base),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "claude_prospector",
                "variance-save",
                "--session-id",
                session_id,
                "--judgment-file",
                str(judgment_file),
                "--data-dir",
                str(claude_data),
            ],
            capture_output=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8")
        written_path = Path(result.stdout.decode("utf-8").strip())
        assert written_path.is_relative_to(
            out_base
        ), f"Written path {written_path} should be under out_base {out_base}"
        assert not written_path.is_relative_to(
            claude_data
        ), f"Written path {written_path} must NOT be under claude_data {claude_data}"

    def test_data_dir_default_is_dot_claude(self) -> None:
        """--data-dir default in the parser must be Path.home() / '.claude'."""
        import argparse

        mod = _import_variance_save()
        top_parser = argparse.ArgumentParser()
        subparsers = top_parser.add_subparsers()
        mod.build_parser(subparsers)
        args = top_parser.parse_args(
            [
                "variance-save",
                "--session-id",
                "dummy",
                "--judgment-file",
                "/dev/null",
            ]
        )
        expected_default = Path.home() / ".claude"
        assert (
            args.data_dir == expected_default
        ), f"Expected data_dir default {expected_default}, got {args.data_dir}"


# ===========================================================================
# TestTimestampProducer — Phase 0: timestamp derivation in save_variance_record
# ===========================================================================


def _user_line_with_ts(
    text: str,
    timestamp: str,
    session_id: str = "test-session",
) -> dict:
    """Build a minimal user message dict with a top-level timestamp.

    Args:
        text: Plain-text message content.
        timestamp: ISO-8601 timestamp string.
        session_id: The session identifier string.

    Returns:
        A dict shaped like a real Claude Code JSONL user entry with
        a top-level ``"timestamp"`` key.
    """
    return {
        "type": "user",
        "userType": "external",
        "sessionId": session_id,
        "timestamp": timestamp,
        "message": {"role": "user", "content": text},
    }


class TestTimestampProducer:
    """save_variance_record must compute earliest transcript timestamp.

    Phase 0 regression tests:
    - Earliest timestamp from raw entry dicts is written to the record.
    - When no entry carries a timestamp, the field is null.
    - The saved record JSON file includes the ``timestamp`` key.
    """

    @pytest.fixture()
    def transcript_with_timestamps(
        self,
        tmp_path: Path,
    ) -> tuple[Path, str]:
        """Transcript where entries carry ``timestamp`` keys.

        Two entries: later timestamp first, earlier timestamp second.
        The producer must pick the earliest (second entry).

        Returns:
            Tuple of ``(data_dir, session_id)``.
        """
        session_id = "ts-session-001"
        project_dir = tmp_path / "projects" / "C--ts-project"
        project_dir.mkdir(parents=True)
        transcript = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            transcript,
            [
                _user_line_with_ts(
                    "Later ask.",
                    "2026-03-10T12:00:00Z",
                    session_id=session_id,
                ),
                _user_line_with_ts(
                    "Earlier ask.",
                    "2026-03-10T09:15:30Z",
                    session_id=session_id,
                ),
                _assistant_with_edit("Edit", "src/foo.py", session_id=session_id),
            ],
        )
        return tmp_path, session_id

    @pytest.fixture()
    def transcript_without_timestamps(
        self,
        tmp_path: Path,
    ) -> tuple[Path, str]:
        """Transcript where no entry carries a ``timestamp`` key.

        Returns:
            Tuple of ``(data_dir, session_id)``.
        """
        session_id = "no-ts-session-001"
        project_dir = tmp_path / "projects" / "C--no-ts-project"
        project_dir.mkdir(parents=True)
        transcript = project_dir / f"{session_id}.jsonl"
        _write_jsonl(
            transcript,
            [
                _user_line("Build it.", session_id=session_id),
                _assistant_with_edit("Edit", "src/bar.py", session_id=session_id),
            ],
        )
        return tmp_path, session_id

    def test_earliest_timestamp_written_to_record(
        self,
        transcript_with_timestamps: tuple[Path, str],
        good_judgment: dict,
    ) -> None:
        """Record timestamp equals the earliest entry timestamp in the transcript."""
        data_dir, session_id = transcript_with_timestamps
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=good_judgment,
            out_base_dir=data_dir,
        )
        with open(out_path, encoding="utf-8") as fh:
            record = json.load(fh)
        # Earliest raw entry is "2026-03-10T09:15:30Z" → normalised UTC
        assert record["timestamp"] is not None
        assert "2026-03-10" in record["timestamp"]
        assert "09:15:30" in record["timestamp"]

    def test_timestamp_is_utc_iso_string(
        self,
        transcript_with_timestamps: tuple[Path, str],
        good_judgment: dict,
    ) -> None:
        """Record timestamp is a valid ISO-8601 UTC string (parseable)."""
        from datetime import datetime

        data_dir, session_id = transcript_with_timestamps
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=good_judgment,
            out_base_dir=data_dir,
        )
        with open(out_path, encoding="utf-8") as fh:
            record = json.load(fh)
        ts = record["timestamp"]
        assert ts is not None
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None, "timestamp must be tz-aware"

    def test_timestamp_null_when_no_entries_carry_timestamp(
        self,
        transcript_without_timestamps: tuple[Path, str],
        good_judgment: dict,
    ) -> None:
        """timestamp is null when no transcript entry carries a timestamp key."""
        data_dir, session_id = transcript_without_timestamps
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=good_judgment,
            out_base_dir=data_dir,
        )
        with open(out_path, encoding="utf-8") as fh:
            record = json.load(fh)
        assert record["timestamp"] is None

    def test_record_json_includes_timestamp_key(
        self,
        transcript_with_timestamps: tuple[Path, str],
        good_judgment: dict,
    ) -> None:
        """Written JSON record must always contain the 'timestamp' key."""
        data_dir, session_id = transcript_with_timestamps
        mod = _import_variance_save()
        out_path = mod.save_variance_record(
            session_id=session_id,
            data_dir=data_dir,
            judgment=good_judgment,
            out_base_dir=data_dir,
        )
        with open(out_path, encoding="utf-8") as fh:
            record = json.load(fh)
        assert "timestamp" in record
