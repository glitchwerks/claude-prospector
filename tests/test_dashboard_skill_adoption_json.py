"""Tests for ``by_skill_adoption`` in the ``dashboard --format json`` payload
(issue #256).

Pins two contracts the current ``dashboard`` ``--format json`` path violates:

- ``by_skill_adoption`` must appear in the JSON payload whenever
  skill-tracking data is present -- unconditionally, unlike
  ``by_mcp_usage`` (which is flag-gated). ``renderer.py`` already includes
  the equivalent key in its ``window.DATA`` blob for HTML rendering; the
  JSON payload should carry the same field for parity.
- On a ``--window`` run, ``by_skill_adoption`` must be computed against the
  *resolved* date bounds ``aggregate()`` uses for call-volume numbers, not
  the raw (unresolved, ``None``) ``--from``/``--to`` args -- mirroring the
  same D-C-style bug class already regression-tested for ``by_mcp_usage``
  in ``tests/test_dashboard_mcp_usage.py::test_t14_...``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``claude_prospector`` as a module and capture output.

    Mirrors ``tests/test_dashboard_mcp_usage.py``'s subprocess pattern,
    including the explicit ``cwd`` so the test is correct regardless of
    which directory pytest was invoked from.

    Args:
        *args: Command-line arguments to pass after the module name.

    Returns:
        CompletedProcess with stdout, stderr, and returncode populated.
    """
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )


def _write_skill_tracking(data_dir: Path, events: list[dict]) -> None:
    """Write a ``skill-tracking.jsonl`` file directly under ``data_dir``.

    Mirrors the flat-file fixture shape used by
    ``tests/test_skill_tracking.py`` and ``tests/test_e2e.py``.

    Args:
        data_dir: Directory to write ``skill-tracking.jsonl`` into.
        events: One dict per JSONL line (each a ``skill_passed`` or
            ``skill_invoked`` event).
    """
    log = data_dir / "skill-tracking.jsonl"
    log.write_text("\n".join(json.dumps(event) for event in events) + "\n")


def _iso(dt: datetime) -> str:
    """Format a UTC datetime as the ``skill-tracking.jsonl`` timestamp shape."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Bug 1 -- by_skill_adoption missing from the --format json payload
# ---------------------------------------------------------------------------


def test_by_skill_adoption_key_present_in_json_payload_when_data_exists(
    tmp_path: Path,
) -> None:
    """dashboard --format json must include a populated "by_skill_adoption"
    key when skill-tracking data exists -- currently silently dropped
    (the payload dict built for --format json never sets this key, unlike
    renderer.py's equivalent HTML data dict).
    """
    _write_skill_tracking(
        tmp_path,
        [
            {
                "event": "skill_passed",
                "skill": "python",
                "target_agent": "code-writer",
                "timestamp": "2026-04-09T21:00:00Z",
                "session_id": "s1",
            },
            {
                "event": "skill_invoked",
                "skill": "python",
                "timestamp": "2026-04-09T21:01:00Z",
                "session_id": "s1",
            },
        ],
    )

    result = _run_cli(
        "dashboard",
        "--data-dir",
        str(tmp_path),
        "--format",
        "json",
    )

    assert result.returncode == 0, (
        f"dashboard --format json exited {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )

    payload = json.loads(result.stdout)

    assert "by_skill_adoption" in payload, (
        "--format json must include 'by_skill_adoption' when "
        "skill-tracking data exists -- renderer.py already includes the "
        "equivalent key in its HTML data dict; the JSON payload dropped "
        "it entirely."
    )
    assert payload["by_skill_adoption"]["python"]["times_passed"] == 1
    assert payload["by_skill_adoption"]["python"]["times_invoked"] == 1
    assert payload["by_skill_adoption"]["python"]["adoption_rate"] == 1.0


def test_by_skill_adoption_key_present_even_with_no_tracking_data(
    tmp_path: Path,
) -> None:
    """dashboard --format json must include "by_skill_adoption" (as {})
    even when NO skill-tracking.jsonl exists at all -- it must be present
    unconditionally, not gated on "there is tracking data" (unlike
    ``by_mcp_usage``, which IS legitimately flag-gated). Without this,
    an implementation could satisfy the "key present when data exists"
    test above by wrapping the payload assignment in
    ``if passed or invoked:``, which would still gate the key on data
    presence rather than including it unconditionally as the aggregator's
    ``field(default_factory=dict)`` default implies.
    """
    # Deliberately no skill-tracking.jsonl written into tmp_path.
    result = _run_cli(
        "dashboard",
        "--data-dir",
        str(tmp_path),
        "--format",
        "json",
    )

    assert result.returncode == 0, (
        f"dashboard --format json exited {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )

    payload = json.loads(result.stdout)

    assert "by_skill_adoption" in payload, (
        "'by_skill_adoption' must be present unconditionally, even with "
        "zero skill-tracking data -- it must not be gated behind a "
        "'there is tracking data' check the way 'by_mcp_usage' is gated "
        "behind '--track-mcp-calls'."
    )
    assert payload["by_skill_adoption"] == {}


# ---------------------------------------------------------------------------
# Bug 2 -- compute_skill_adoption() gets raw args instead of resolved bounds
# ---------------------------------------------------------------------------


def test_by_skill_adoption_on_window_run_excludes_out_of_window_events(
    tmp_path: Path,
) -> None:
    """dashboard --window 7d --format json must compute by_skill_adoption
    against the SAME resolved date bounds aggregate() uses for call-volume
    numbers -- not the raw, unresolved --from/--to args (which stay None
    on a --window run, so compute_skill_adoption() currently gets no
    bounds at all and includes events far outside the window).

    Two skills are passed under two different names so presence/absence
    in the payload -- not just a count -- proves the window was applied:
    a skill passed 1 day ago must show up; a skill passed 30 days ago
    must not, under --window 7d.
    """
    now = datetime.now(timezone.utc)
    in_window = now - timedelta(days=1)
    out_of_window = now - timedelta(days=30)

    _write_skill_tracking(
        tmp_path,
        [
            {
                "event": "skill_passed",
                "skill": "in-window-skill",
                "target_agent": "code-writer",
                "timestamp": _iso(in_window),
                "session_id": "s-recent",
            },
            {
                "event": "skill_passed",
                "skill": "out-of-window-skill",
                "target_agent": "code-writer",
                "timestamp": _iso(out_of_window),
                "session_id": "s-old",
            },
        ],
    )

    # Sanity check: with no time-scoping flags at all, both skills must
    # appear -- otherwise a failure below could just mean the fixture
    # itself is broken, not that windowing is broken.
    unscoped = _run_cli(
        "dashboard",
        "--data-dir",
        str(tmp_path),
        "--format",
        "json",
    )
    assert unscoped.returncode == 0, (
        f"dashboard --format json exited {unscoped.returncode}.\n"
        f"stderr: {unscoped.stderr}"
    )
    unscoped_adoption = json.loads(unscoped.stdout).get("by_skill_adoption", {})
    assert "in-window-skill" in unscoped_adoption, (
        "fixture sanity check failed -- the recent skill_passed event did "
        f"not appear at all in an unscoped run: {unscoped_adoption!r}"
    )
    assert "out-of-window-skill" in unscoped_adoption, (
        "fixture sanity check failed -- the older skill_passed event did "
        f"not appear at all in an unscoped run: {unscoped_adoption!r}"
    )

    windowed = _run_cli(
        "dashboard",
        "--data-dir",
        str(tmp_path),
        "--format",
        "json",
        "--window",
        "7d",
    )
    assert windowed.returncode == 0, (
        f"dashboard --window 7d --format json exited {windowed.returncode}.\n"
        f"stderr: {windowed.stderr}"
    )

    windowed_adoption = json.loads(windowed.stdout).get("by_skill_adoption", {})

    assert "in-window-skill" in windowed_adoption, (
        "--window 7d must still include a skill passed 1 day ago -- got "
        f"{windowed_adoption!r}"
    )
    assert "out-of-window-skill" not in windowed_adoption, (
        "--window 7d must exclude a skill passed 30 days ago -- "
        "compute_skill_adoption() must be called with the SAME resolved "
        "from/to bounds aggregate() uses, not the raw (unresolved, None) "
        f"--from/--to args. Got: {windowed_adoption!r}"
    )
