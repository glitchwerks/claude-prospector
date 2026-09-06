"""Regression test for the dashboard JSON contract snapshot.

The fixture originated before the subparser refactor and is updated when an
intentional additive schema change is approved.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "session_summaries"
    / "dashboard_baseline_input"
)
SNAPSHOT_FILE = (
    Path(__file__).parent / "fixtures" / "dashboard_snapshot_pre_refactor.json"
)

# Repo root resolved from this file's location, so pytest invoked from any
# directory (main checkout, worktree, /tmp) uses the correct tree.  Without an
# explicit cwd=, the subprocess inherits the test-runner's CWD and can silently
# pass when invoked from a sibling checkout that happens to have the same
# module importable but different fixture data.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dashboard_json_matches_contract_snapshot() -> None:
    """Dashboard JSON output must match the current committed contract snapshot.

    Runs the dashboard subcommand against the committed minimal fixture
    tree and compares stdout to the committed snapshot. Any unapproved diff
    indicates a behavior regression or an undocumented schema change.

    Note: generated_at will differ between runs (it is the current
    timestamp). The comparison therefore normalises that field to a
    fixed sentinel before comparing, so only structural/data differences
    trigger a failure.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "claude_prospector",
            "dashboard",
            "--from",
            "2026-01-01",
            "--to",
            "2026-12-31",
            "--format",
            "json",
            "--data-dir",
            str(FIXTURE_DIR),
        ],
        capture_output=True,
        text=True,
        # Explicit cwd ensures the subprocess resolves sys.path against the
        # correct repo root regardless of where pytest was invoked from.
        cwd=str(_REPO_ROOT),
    )
    assert (
        result.returncode == 0
    ), f"dashboard exited {result.returncode}.\nstderr: {result.stderr}"

    actual = json.loads(result.stdout)
    expected = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))

    # Normalise the timestamp field — it will differ between runs.
    actual["generated_at"] = "__normalised__"
    expected["generated_at"] = "__normalised__"

    assert actual == expected, (
        "Dashboard JSON output differs from the contract snapshot.\n"
        "If this is intentional, document the schema change and commit the "
        "updated snapshot."
    )
