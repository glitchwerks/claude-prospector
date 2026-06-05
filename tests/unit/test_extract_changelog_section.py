"""Tests for scripts/extract-changelog-section.py.

Covers: normal extraction, missing version, first version (no next heading),
multiple versions in file, CLI exit code, and blank/whitespace trimming.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "extract-changelog-section.py"

# ---------------------------------------------------------------------------
# Fixture CHANGELOG content used across tests
# ---------------------------------------------------------------------------

_SAMPLE_CHANGELOG = textwrap.dedent(
    """\
    # Changelog

    All notable changes to this project will be documented in this file.

    ## [Unreleased]

    ## [0.10.0] - 2026-05-30

    ### Added

    - Added `audit` subcommand (closes #191).
    - **cwd-first project names** in the dashboard (#203, closes #205).

    ### Fixed

    - **Today/daily activity bucketed by local timezone** (#197, closes #199).

    ## [0.9.1] - 2026-05-26

    ### Fixed

    - **Dashboard `--window` no longer filters out prior-period data** (#188).

    ## [0.9.0] - 2026-05-26

    ### Added

    - **Economy v1 dashboard** (#144).

    [0.10.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.10.0
    [0.9.1]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.9.1
    [0.9.0]: https://github.com/glitchwerks/claude-prospector/releases/tag/v0.9.0
    """
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_script(
    changelog_text: str,
    version: str,
    tmp_path: Path,
) -> subprocess.CompletedProcess:
    """Write a temporary CHANGELOG and run the extractor against it.

    Args:
        changelog_text: Full text content of the CHANGELOG.
        version: Version string to extract (e.g. ``"0.10.0"``).
        tmp_path: Pytest temporary directory for the CHANGELOG file.

    Returns:
        The ``CompletedProcess`` result from the script invocation.
    """
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(changelog_text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(_SCRIPT), version, str(changelog_path)],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtractChangelogSection:
    """Unit tests for the changelog section extractor."""

    def test_extracts_middle_version(self, tmp_path: Path) -> None:
        """Extracts the content of 0.9.1 (sandwiched between two other versions)."""
        result = _run_script(_SAMPLE_CHANGELOG, "0.9.1", tmp_path)
        assert result.returncode == 0, result.stderr
        output = result.stdout.strip()
        # Should contain the 0.9.1 content
        assert "Dashboard `--window`" in output
        assert "#188" in output
        # Should NOT contain content from 0.10.0 or 0.9.0
        assert "audit" not in output
        assert "Economy v1" not in output

    def test_extracts_latest_version(self, tmp_path: Path) -> None:
        """Extracts the latest (most recent) version section at the top."""
        result = _run_script(_SAMPLE_CHANGELOG, "0.10.0", tmp_path)
        assert result.returncode == 0, result.stderr
        output = result.stdout.strip()
        assert "audit" in output
        assert "closes #191" in output
        # Must not bleed into 0.9.1
        assert "Dashboard `--window`" not in output

    def test_extracts_oldest_version(self, tmp_path: Path) -> None:
        """Extracts the last version in the file (no following ## heading)."""
        result = _run_script(_SAMPLE_CHANGELOG, "0.9.0", tmp_path)
        assert result.returncode == 0, result.stderr
        output = result.stdout.strip()
        assert "Economy v1" in output
        assert "#144" in output
        # Must not include the link reference section
        assert "https://github.com" not in output

    def test_strips_leading_and_trailing_blank_lines(self, tmp_path: Path) -> None:
        """Output has no leading or trailing blank lines."""
        result = _run_script(_SAMPLE_CHANGELOG, "0.9.1", tmp_path)
        assert result.returncode == 0, result.stderr
        output = result.stdout
        assert not output.startswith("\n")
        assert output.endswith("\n") or output == output.strip()

    def test_missing_version_exits_nonzero(self, tmp_path: Path) -> None:
        """Exits with a non-zero code and writes an error if version not found."""
        result = _run_script(_SAMPLE_CHANGELOG, "1.99.0", tmp_path)
        assert result.returncode != 0
        assert "1.99.0" in result.stderr or "not found" in result.stderr.lower()

    def test_version_with_v_prefix_accepted(self, tmp_path: Path) -> None:
        """Version prefixed with 'v' (e.g. v0.10.0) is accepted and normalised."""
        result = _run_script(_SAMPLE_CHANGELOG, "v0.10.0", tmp_path)
        assert result.returncode == 0, result.stderr
        assert "audit" in result.stdout

    def test_missing_changelog_file_exits_nonzero(self, tmp_path: Path) -> None:
        """Exits with a non-zero code when the CHANGELOG file does not exist."""
        missing = tmp_path / "DOES_NOT_EXIST.md"
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "0.10.0", str(missing)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
