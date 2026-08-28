"""Tests for Phase 1 of the MCP tool-usage dashboard panel (issue #248).

Pins the Phase 1 contract for issue #248 (implemented in PR #260) before
any of it is implemented:

- ``AggregateResult.by_mcp_usage`` field (``aggregator.py``).
- ``dashboard --track-mcp-calls`` flag (``cli/dashboard.py build_parser``),
  default ``False``.
- Flag-gated collection wiring in ``dashboard run()`` -- off means
  ``collect_per_session`` is never called and ``by_mcp_usage`` stays ``{}``.
- ``by_mcp_usage`` appears unconditionally in ``renderer.py``'s ``data``
  dict (``window.DATA``), but only in ``--format json``'s ``payload`` when
  the flag is set (F8's byte-identical guarantee for existing consumers).
- The exact §4.3 JSON shape: ``by_tool``, ``by_server``,
  ``availability_signal``, ``warnings``, ``window`` -- with ``by_agent`` and
  ``compact`` absent, not empty.

Test names carry the plan's T-numbers (§6) so failures trace back to the
requirement they pin. T1/T4/T7/T9/T11/T12/T13 are not repeated here --
T1/T13 are Phase 0 gates already covered by
``tests/unit/test_tool_collection.py`` and ``tests/unit/test_tool_usage.py``;
T4 is the existing, unmodified
``tests/test_cli_subcommands.py::TestToolUsageSubcommand::test_track_mcp_calls_flag_is_rejected``;
T7 only applies under D-C=(a), which was not chosen (D-C=(b)); T9/T11/T12
are Phase 2 (view-layer) gates.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from claude_prospector.aggregator import AggregateResult
from claude_prospector.cli.dashboard import build_parser
from claude_prospector.renderer import render

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "session_summaries"
    / "mcp_usage_dashboard_input"
)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``claude_prospector`` as a module and capture output.

    Mirrors ``tests/test_dashboard_snapshot.py``'s subprocess pattern,
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


def _extract_window_data(html: str) -> dict:
    """Extract and parse the embedded ``window.DATA = {...}`` JSON payload.

    Mirrors the marker-search-then-raw_decode pattern already used by
    ``tests/test_renderer.py``.

    Args:
        html: Full rendered dashboard HTML.

    Returns:
        The parsed ``DATA`` object.

    Raises:
        AssertionError: If neither the ``window.DATA = `` nor legacy
            ``const DATA = `` marker is present.
    """
    for marker in ("window.DATA = ", "const DATA = "):
        if marker in html:
            data_start = html.index(marker) + len(marker)
            decoder = json.JSONDecoder()
            data_obj, _ = decoder.raw_decode(html, data_start)
            return data_obj
    raise AssertionError(
        "Neither 'window.DATA = ' nor 'const DATA = ' found in rendered "
        "HTML; the data embedding contract has changed."
    )


def _dashboard_args(
    output: Path,
    data_dir: Path,
    *,
    track_mcp_calls: bool,
    track_mcp_call_sizes: bool = False,
) -> argparse.Namespace:
    """Build a minimal Namespace for the dashboard ``run()`` handler.

    Mirrors ``tests/test_cli_dashboard_default.py``'s ``_make_args`` helper,
    plus the ``track_mcp_calls`` field Phase 1 adds and the
    ``track_mcp_call_sizes`` field Phase 3 wires up (issue #262). The new
    field defaults to False so every pre-existing call site in this file
    keeps constructing a valid Namespace without modification -- Phase 3's
    ``run()`` reads ``args.track_mcp_call_sizes`` unconditionally (it must
    also gate collection when ``--track-mcp-calls`` is absent, per the D-4
    "independent secondary flag" resolution), so a Namespace missing the
    attribute would now raise AttributeError instead of the pre-Phase-3
    behavior.

    Args:
        output: Value for ``args.output`` -- the HTML file to write.
        data_dir: Value for ``args.data_dir``.
        track_mcp_calls: Value for the ``--track-mcp-calls`` flag.
        track_mcp_call_sizes: Value for the ``--track-mcp-call-sizes``
            flag. Defaults to False.

    Returns:
        An ``argparse.Namespace`` suitable for passing to ``run()``.
    """
    return argparse.Namespace(
        data_dir=data_dir,
        from_date=None,
        to_date=None,
        window=None,
        output=output,
        no_open=True,
        limit_5h=None,
        limit_7d=None,
        limit_sonnet_7d=None,
        output_format="html",
        track_mcp_calls=track_mcp_calls,
        track_mcp_call_sizes=track_mcp_call_sizes,
    )


# ---------------------------------------------------------------------------
# T2 / T3 -- flag parsing
# ---------------------------------------------------------------------------


class TestTrackMcpCallsFlagParsing:
    """dashboard --track-mcp-calls: default False, accepted when passed."""

    def test_t2_defaults_to_false_when_absent(self) -> None:
        """T2: track_mcp_calls is False when --track-mcp-calls is omitted."""
        top = argparse.ArgumentParser()
        sub = top.add_subparsers()
        build_parser(sub)
        args = top.parse_args(["dashboard"])
        assert args.track_mcp_calls is False

    def test_t3_flag_is_accepted_and_sets_true(self) -> None:
        """T3: --track-mcp-calls parses without error and sets True."""
        top = argparse.ArgumentParser()
        sub = top.add_subparsers()
        build_parser(sub)
        args = top.parse_args(["dashboard", "--track-mcp-calls"])
        assert args.track_mcp_calls is True


# ---------------------------------------------------------------------------
# T5 -- flag off means no collection and by_mcp_usage stays {}
# ---------------------------------------------------------------------------


def test_t5_flag_off_skips_collection_and_by_mcp_usage_stays_empty(
    tmp_path: Path,
) -> None:
    """T5: with the flag off, collect_per_session is never called and
    by_mcp_usage stays {} in the rendered data -- even though the fixture
    data dir contains a session with a real MCP tool call, proving this
    is the flag suppressing collection, not an empty fixture.

    Patch target is claude_prospector.tool_collection.collect_per_session
    (not claude_prospector.cli.dashboard.collect_per_session), per the
    plan's T5 note: Phase 1 uses a function-local lazy import, so the name
    is looked up in the source module at call time.
    """
    from claude_prospector.cli.dashboard import run

    output = tmp_path / "dashboard.html"
    args = _dashboard_args(output, _FIXTURE_DIR, track_mcp_calls=False)

    with patch("claude_prospector.tool_collection.collect_per_session") as spy:
        exit_code = run(args)

    assert exit_code == 0
    spy.assert_not_called()

    html = output.read_text(encoding="utf-8")
    data_obj = _extract_window_data(html)
    assert "by_mcp_usage" in data_obj, (
        "renderer's window.DATA must carry by_mcp_usage unconditionally "
        "(F4), even with the flag off."
    )
    assert data_obj["by_mcp_usage"] == {}, (
        "With --track-mcp-calls off, by_mcp_usage must stay {} (F3) -- "
        f"got {data_obj['by_mcp_usage']!r}."
    )


# ---------------------------------------------------------------------------
# T6 -- JSON payload gating (F8)
# ---------------------------------------------------------------------------


def test_t6_json_payload_gates_by_mcp_usage_on_the_flag() -> None:
    """T6: --format json --track-mcp-calls emits by_mcp_usage; --format json
    alone omits the key entirely (not {}), protecting F8's byte-identical
    guarantee for existing --format json consumers.
    """
    with_flag = _run_cli(
        "dashboard",
        "--data-dir",
        str(_FIXTURE_DIR),
        "--format",
        "json",
        "--track-mcp-calls",
    )
    without_flag = _run_cli(
        "dashboard",
        "--data-dir",
        str(_FIXTURE_DIR),
        "--format",
        "json",
    )

    assert with_flag.returncode == 0, (
        f"dashboard --track-mcp-calls exited {with_flag.returncode}.\n"
        f"stderr: {with_flag.stderr}"
    )
    assert without_flag.returncode == 0, (
        f"dashboard --format json exited {without_flag.returncode}.\n"
        f"stderr: {without_flag.stderr}"
    )

    payload_with = json.loads(with_flag.stdout)
    payload_without = json.loads(without_flag.stdout)

    assert "by_mcp_usage" in payload_with
    assert "by_mcp_usage" not in payload_without, (
        "--format json without --track-mcp-calls must omit by_mcp_usage "
        "entirely, not emit it as {} -- F8 requires byte-identical output "
        "for existing consumers."
    )


# ---------------------------------------------------------------------------
# T8 -- renderer always carries by_mcp_usage in window.DATA
# ---------------------------------------------------------------------------


def test_t8_renderer_embeds_by_mcp_usage_key_unconditionally(
    tmp_path: Path,
) -> None:
    """T8: render()'s window.DATA carries by_mcp_usage even for a default
    (empty) AggregateResult -- it is an internal surface (F4), unlike the
    --format json payload, which is flag-gated (see T6).
    """
    result = AggregateResult()
    output = tmp_path / "dashboard.html"
    render(result, output_path=output, open_browser=False)
    html = output.read_text(encoding="utf-8")

    data_obj = _extract_window_data(html)
    assert "by_mcp_usage" in data_obj, (
        "window.DATA must carry by_mcp_usage unconditionally, present "
        "even when the AggregateResult's value is the default {}."
    )


def test_t8_renderer_embeds_by_mcp_usage_content_verbatim(
    tmp_path: Path,
) -> None:
    """T8 (content variant): a non-empty by_mcp_usage on the AggregateResult
    passed to render() round-trips into window.DATA unchanged.

    Constructing AggregateResult(by_mcp_usage=...) exercises the new
    dataclass field directly (F2's storage location), distinct from the
    renderer-wiring check above.
    """
    usage = {
        "by_tool": {"mcp__demo-server__do_thing": 3},
        "by_server": {},
        "availability_signal": {},
        "warnings": {"malformed_mcp_names": 0, "unreadable_transcripts": 0},
        "window": {"start": None, "end": None, "sessions": 1, "sessions_skipped": 0},
    }
    result = AggregateResult(by_mcp_usage=usage)
    output = tmp_path / "dashboard.html"
    render(result, output_path=output, open_browser=False)
    html = output.read_text(encoding="utf-8")

    data_obj = _extract_window_data(html)
    assert data_obj["by_mcp_usage"] == usage


# ---------------------------------------------------------------------------
# T10 -- session-scope denominator (D-B=(a))
# ---------------------------------------------------------------------------


def test_t10_session_scope_denominator_matches_total_sessions() -> None:
    """T10: by_mcp_usage.window.sessions equals result.total_sessions --
    the in-window session-id set fed to collect_per_session /
    compute_tool_usage is exactly {s["session_id"] for s in result.sessions}
    (D-B=(a)), so the two numbers can never silently disagree.
    """
    result = _run_cli(
        "dashboard",
        "--data-dir",
        str(_FIXTURE_DIR),
        "--format",
        "json",
        "--track-mcp-calls",
    )

    assert result.returncode == 0, (
        f"dashboard --track-mcp-calls exited {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )

    payload = json.loads(result.stdout)

    # Sanity: the fixture's one session must actually be counted, or the
    # equality below would be a trivial 0 == 0.
    assert payload["total_sessions"] >= 1, (
        "fixture sanity check failed -- expected at least one session in "
        f"the all-time (no --from/--to/--window) run, got "
        f"{payload['total_sessions']!r}"
    )
    assert payload["by_mcp_usage"]["window"]["sessions"] == payload["total_sessions"], (
        "by_mcp_usage.window.sessions must equal result.total_sessions "
        "(the D-B=(a) denominator invariant) -- got "
        f"{payload['by_mcp_usage']['window']['sessions']!r} vs "
        f"{payload['total_sessions']!r}"
    )


# ---------------------------------------------------------------------------
# T14 -- resolved time bounds (Phase 1 step 2b)
# ---------------------------------------------------------------------------


def test_t14_window_bounds_are_resolved_not_raw_args() -> None:
    """T14: dashboard --window 7d --track-mcp-calls --format json resolves
    by_mcp_usage.window.start to a real date, not null; a run with no time
    flags emits null/null for both. Guards the D-C finding-2 bug class
    (args.from_date left None on --window runs) from recurring on this
    new field.
    """
    windowed = _run_cli(
        "dashboard",
        "--data-dir",
        str(_FIXTURE_DIR),
        "--format",
        "json",
        "--track-mcp-calls",
        "--window",
        "7d",
    )
    no_time_flags = _run_cli(
        "dashboard",
        "--data-dir",
        str(_FIXTURE_DIR),
        "--format",
        "json",
        "--track-mcp-calls",
    )

    assert windowed.returncode == 0, (
        f"dashboard --window 7d --track-mcp-calls exited "
        f"{windowed.returncode}.\nstderr: {windowed.stderr}"
    )
    assert no_time_flags.returncode == 0, (
        f"dashboard --track-mcp-calls exited {no_time_flags.returncode}.\n"
        f"stderr: {no_time_flags.stderr}"
    )

    windowed_payload = json.loads(windowed.stdout)
    no_flags_payload = json.loads(no_time_flags.stdout)

    assert windowed_payload["by_mcp_usage"]["window"]["start"] is not None, (
        "--window 7d must resolve by_mcp_usage.window.start to a real "
        "date, not null -- resolved bounds must be computed once and "
        "reused for both aggregate() and the by_mcp_usage.window block."
    )
    assert no_flags_payload["by_mcp_usage"]["window"]["start"] is None
    assert no_flags_payload["by_mcp_usage"]["window"]["end"] is None


# ---------------------------------------------------------------------------
# T15 -- exact payload shape (D-K / §4.3)
# ---------------------------------------------------------------------------


def test_t15_by_mcp_usage_has_exactly_the_five_documented_keys() -> None:
    """T15: by_mcp_usage contains exactly by_tool, by_server,
    availability_signal, warnings, window -- by_agent and compact are
    absent entirely, not present-and-empty.
    """
    result = _run_cli(
        "dashboard",
        "--data-dir",
        str(_FIXTURE_DIR),
        "--format",
        "json",
        "--track-mcp-calls",
    )

    assert result.returncode == 0, (
        f"dashboard --track-mcp-calls exited {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )

    usage = json.loads(result.stdout)["by_mcp_usage"]

    assert set(usage.keys()) == {
        "by_tool",
        "by_server",
        "availability_signal",
        "warnings",
        "window",
    }, f"by_mcp_usage has an unexpected key set: {sorted(usage.keys())!r}"
    assert "by_agent" not in usage, "by_agent must be omitted (D-F=(a)), not {}"
    assert "compact" not in usage, "compact must be omitted -- no dashboard flag exists"
