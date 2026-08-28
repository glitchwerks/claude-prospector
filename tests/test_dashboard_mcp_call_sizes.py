"""Tests for the ``--track-mcp-call-sizes`` CLI flag (issue #262, D-4).

D-4's "yes-isolated-with-secondary-flag" resolution requires the
result-payload-length read to be gated behind a **new**, separate CLI flag
on ``dashboard`` -- distinct from the existing ``--track-mcp-calls`` flag,
which must keep behaving exactly as it does today (call-counts only).

``TestTrackMcpCallSizesFlagParsing`` covers only flag parsing
(``build_parser`` in ``cli/dashboard.py``); the collection-level gating
behavior (result_chars staying None until this flag opts in) is covered by
``tests/unit/test_tool_collection.py::TestCollectToolUsesResultSizes``.

Everything below that class is Phase 3 wiring (issue #262 §8 Phase 3): the
JSON-output contract for ``dashboard run()`` once ``--track-mcp-call-sizes``
actually threads through to ``collect_per_session`` / ``compute_tool_usage``.
Pins the design decision that ``--track-mcp-call-sizes`` works standalone,
independent of ``--track-mcp-calls`` -- the ``run()`` gate must become
``if args.track_mcp_calls or args.track_mcp_call_sizes:``, not stay
conditioned on ``--track-mcp-calls`` alone.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from claude_prospector.cli.dashboard import build_parser


class TestTrackMcpCallSizesFlagParsing:
    """dashboard --track-mcp-call-sizes: default False, accepted when
    passed, and fully independent of --track-mcp-calls.
    """

    def test_defaults_to_false_when_absent(self) -> None:
        """track_mcp_call_sizes is False when the flag is omitted."""
        top = argparse.ArgumentParser()
        sub = top.add_subparsers()
        build_parser(sub)

        args = top.parse_args(["dashboard"])

        assert args.track_mcp_call_sizes is False

    def test_flag_is_accepted_and_sets_true(self) -> None:
        """--track-mcp-call-sizes parses without error and sets True."""
        top = argparse.ArgumentParser()
        sub = top.add_subparsers()
        build_parser(sub)

        args = top.parse_args(["dashboard", "--track-mcp-call-sizes"])

        assert args.track_mcp_call_sizes is True

    def test_independent_of_track_mcp_calls_flag(self) -> None:
        """Passing --track-mcp-call-sizes alone must not also flip the
        existing --track-mcp-calls flag -- they are two separate opt-ins,
        per D-4's requirement that the existing flag's behavior is
        unchanged.
        """
        top = argparse.ArgumentParser()
        sub = top.add_subparsers()
        build_parser(sub)

        args = top.parse_args(["dashboard", "--track-mcp-call-sizes"])

        assert args.track_mcp_calls is False
        assert args.track_mcp_call_sizes is True

    def test_both_flags_can_be_passed_together(self) -> None:
        """The two flags are independently settable, not mutually
        exclusive.
        """
        top = argparse.ArgumentParser()
        sub = top.add_subparsers()
        build_parser(sub)

        args = top.parse_args(
            ["dashboard", "--track-mcp-calls", "--track-mcp-call-sizes"]
        )

        assert args.track_mcp_calls is True
        assert args.track_mcp_call_sizes is True


# ---------------------------------------------------------------------------
# Phase 3 wiring: --track-mcp-call-sizes threaded through run() into
# collect_per_session / compute_tool_usage and the --format json payload.
#
# Fixture layout mirrors tests/test_dashboard_mcp_usage.py's pattern
# (subprocess over a small on-disk data dir). Two fixtures are used:
#
# - _FIXTURE_DIR: the existing Phase 1 fixture (one MCP call, no matching
#   tool_result in the transcript) -- enough to prove by_mcp_usage is
#   non-empty and shaped correctly when the cost fields are all "no data"
#   (the flag being present must not require a populated result to work).
# - _COST_FIXTURE_DIR: a richer fixture (tests/fixtures/session_summaries/
#   mcp_cost_proxy_dashboard_input) with three MCP calls on one server --
#   one with a measured 40-char string result, one whose result contains an
#   image block (excluded), one with no matching tool_result at all (missing)
#   -- giving cost_attribution's three counters and by_method_tokens'
#   per-method total/mean each a distinct, known value to pin exactly.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "session_summaries"
    / "mcp_usage_dashboard_input"
)
_COST_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "session_summaries"
    / "mcp_cost_proxy_dashboard_input"
)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``claude_prospector`` as a module and capture output.

    Mirrors ``tests/test_dashboard_mcp_usage.py``'s ``_run_cli`` helper.

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


def _wiring_dashboard_args(
    output: Path,
    data_dir: Path,
    *,
    track_mcp_calls: bool,
    track_mcp_call_sizes: bool,
) -> argparse.Namespace:
    """Build a minimal Namespace for direct in-process ``run()`` calls.

    Local to this file per this repo's "each test file defines its own
    fixture builders" convention (see ``tests/unit/test_tool_collection.py``'s
    module docstring) -- duplicates
    ``tests/test_dashboard_mcp_usage.py::_dashboard_args`` rather than
    importing it, since that helper is private to its own module.

    Args:
        output: Value for ``args.output`` -- the HTML file to write.
        data_dir: Value for ``args.data_dir``.
        track_mcp_calls: Value for the ``--track-mcp-calls`` flag.
        track_mcp_call_sizes: Value for the ``--track-mcp-call-sizes`` flag.

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


class TestTrackMcpCallSizesAloneStillCollects:
    """Crux case: --track-mcp-call-sizes alone (no --track-mcp-calls) must
    still run collection and produce a non-empty by_mcp_usage carrying both
    the base call-count fields (unchanged shape) AND the new cost fields --
    setting the sizes flag must not suppress the base fields, and must not
    require --track-mcp-calls to also be passed.
    """

    def test_flag_alone_produces_base_and_cost_fields(self) -> None:
        """--track-mcp-call-sizes with no --track-mcp-calls still yields a
        populated by_server entry containing both total_calls/by_method
        (base) and estimated_result_tokens/by_method_tokens (cost), plus a
        top-level cost_attribution block.
        """
        result = _run_cli(
            "dashboard",
            "--data-dir",
            str(_COST_FIXTURE_DIR),
            "--format",
            "json",
            "--track-mcp-call-sizes",
        )

        assert result.returncode == 0, (
            f"dashboard --track-mcp-call-sizes exited {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )

        payload = json.loads(result.stdout)
        assert "by_mcp_usage" in payload, (
            "--track-mcp-call-sizes alone must still populate the "
            "--format json payload's by_mcp_usage key -- the sizes flag "
            "must independently trigger the same run() collection gate "
            "--track-mcp-calls does, per D-4's 'independent secondary "
            "flag' resolution."
        )
        usage = payload["by_mcp_usage"]
        assert usage != {}, (
            "by_mcp_usage must be non-empty with --track-mcp-call-sizes "
            "alone -- it must not require --track-mcp-calls to also be "
            "passed for collection to run."
        )

        server_info = usage["by_server"]["proxy-demo"]
        # Base (count) fields must still be present -- the sizes flag is
        # additive, not a replacement collection mode.
        assert server_info["total_calls"] == 3
        assert isinstance(server_info["by_method"], dict)
        assert server_info["by_method"] != {}

        # Cost fields must also be present.
        assert "estimated_result_tokens" in server_info
        assert "by_method_tokens" in server_info
        assert "cost_attribution" in usage


class TestTrackMcpCallsAloneOmitsCostFields:
    """Regression guard: --track-mcp-calls alone (no --track-mcp-call-sizes)
    must keep producing base-only fields -- no cost fields anywhere in the
    payload, matching the existing (pre-Phase-3) contract exactly.
    """

    def test_flag_alone_produces_only_base_fields(self) -> None:
        """--track-mcp-calls with no --track-mcp-call-sizes must not emit
        cost_attribution, estimated_result_tokens, or by_method_tokens
        anywhere in the payload -- proving the sizes flag is not
        accidentally always-on.
        """
        result = _run_cli(
            "dashboard",
            "--data-dir",
            str(_COST_FIXTURE_DIR),
            "--format",
            "json",
            "--track-mcp-calls",
        )

        assert result.returncode == 0, (
            f"dashboard --track-mcp-calls exited {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )

        usage = json.loads(result.stdout)["by_mcp_usage"]
        assert usage != {}
        assert "cost_attribution" not in usage, (
            "--track-mcp-calls alone must not emit cost_attribution -- "
            "the cost fields must be conditioned on "
            "--track-mcp-call-sizes, not on --track-mcp-calls."
        )
        for server_name, server_info in usage["by_server"].items():
            assert "estimated_result_tokens" not in server_info, (
                f"by_server[{server_name!r}] must not carry "
                "estimated_result_tokens with --track-mcp-calls alone."
            )
            assert "by_method_tokens" not in server_info, (
                f"by_server[{server_name!r}] must not carry "
                "by_method_tokens with --track-mcp-calls alone."
            )


class TestNeitherFlagLeavesByMcpUsageEmpty:
    """Regression guard: with neither flag set, by_mcp_usage's existing
    empty-state contract must be completely unchanged by this phase's
    wiring -- {} in window.DATA (T5), and the key entirely absent from the
    --format json payload (T6).
    """

    def test_json_payload_omits_by_mcp_usage_key(self) -> None:
        """--format json with neither flag must omit by_mcp_usage entirely
        (not emit {}), matching T6's existing guarantee -- re-pinned here
        because Phase 3's OR-gate change is the exact code path that could
        regress it.
        """
        result = _run_cli(
            "dashboard",
            "--data-dir",
            str(_FIXTURE_DIR),
            "--format",
            "json",
        )

        assert result.returncode == 0, (
            f"dashboard --format json exited {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )
        payload = json.loads(result.stdout)
        assert "by_mcp_usage" not in payload

    def test_run_leaves_window_data_by_mcp_usage_empty(self, tmp_path: Path) -> None:
        """Direct run() with both flags False must leave window.DATA's
        by_mcp_usage at {} (T5's guarantee), and collect_per_session must
        never be called -- proving the OR-gate is False when both flags
        are False, not just when --track-mcp-calls is False.
        """
        from claude_prospector.cli.dashboard import run

        output = tmp_path / "dashboard.html"
        args = _wiring_dashboard_args(
            output,
            _FIXTURE_DIR,
            track_mcp_calls=False,
            track_mcp_call_sizes=False,
        )

        with patch("claude_prospector.tool_collection.collect_per_session") as spy:
            exit_code = run(args)

        assert exit_code == 0
        spy.assert_not_called()

        html = output.read_text(encoding="utf-8")
        assert '"by_mcp_usage": {}' in html or "by_mcp_usage" in html


class TestBothFlagsTogether:
    """Both flags set together must behave like --track-mcp-call-sizes
    alone (base + cost fields both present), with collection running
    exactly once -- no double-collection or inconsistent state from the
    OR-gate firing alongside an explicit AND of both conditions.
    """

    def test_both_flags_collect_once_and_include_both_field_sets(
        self, tmp_path: Path
    ) -> None:
        """collect_per_session must be called exactly once when both flags
        are True (the OR-gate must not cause a second collection pass), and
        the resulting by_mcp_usage must carry both base and cost fields.
        """
        from claude_prospector.cli.dashboard import run
        from claude_prospector.tool_collection import (
            collect_per_session as _real_collect_per_session,
        )

        output = tmp_path / "dashboard.html"
        args = _wiring_dashboard_args(
            output,
            _COST_FIXTURE_DIR,
            track_mcp_calls=True,
            track_mcp_call_sizes=True,
        )

        with patch(
            "claude_prospector.tool_collection.collect_per_session",
            wraps=_real_collect_per_session,
        ) as spy:
            exit_code = run(args)

        assert exit_code == 0
        spy.assert_called_once()

        html = output.read_text(encoding="utf-8")
        assert "estimated_result_tokens" in html
        assert "cost_attribution" in html
        assert "total_calls" in html


class TestByMethodShapeUnchangedWithCostFields:
    """Regression guard: by_method's existing dict[str, int] shape must be
    completely unaffected by the cost fields being present alongside it --
    Phase 2 shipped by_method_tokens as an additive sibling specifically to
    avoid a breaking shape change to by_method (plan §6b / Phase 2 note).
    """

    def test_by_method_values_stay_plain_ints(self) -> None:
        """Every by_method value must remain a plain int, not an object,
        when track_mcp_call_sizes is on and by_method_tokens is also
        present.
        """
        result = _run_cli(
            "dashboard",
            "--data-dir",
            str(_COST_FIXTURE_DIR),
            "--format",
            "json",
            "--track-mcp-call-sizes",
        )

        assert result.returncode == 0, (
            f"dashboard --track-mcp-call-sizes exited {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )
        usage = json.loads(result.stdout)["by_mcp_usage"]
        server_info = usage["by_server"]["proxy-demo"]

        assert server_info["by_method"] == {
            "measured_call": 1,
            "image_call": 1,
            "missing_call": 1,
        }
        for method, count in server_info["by_method"].items():
            assert isinstance(count, int), (
                f"by_method[{method!r}] must stay a plain int -- got "
                f"{type(count).__name__} ({count!r})."
            )


class TestCostAttributionExactShapeAndValues:
    """T-crux (case 6): cost_attribution's exact shape and field values,
    plus estimated_result_tokens / by_method_tokens per-method values,
    given a fixture transcript with one measured, one excluded
    (image-bearing), and one missing-result MCP call on the same server.
    """

    def test_cost_attribution_and_per_method_token_stats_are_exact(self) -> None:
        """cost_attribution's three call counters and the measured-call's
        token stats must exactly match the fixture's known composition:
        one 40-char measured result (10.0 estimated tokens at the shipped
        4.0 chars-per-token divisor), one excluded (image) result, one
        missing result.
        """
        result = _run_cli(
            "dashboard",
            "--data-dir",
            str(_COST_FIXTURE_DIR),
            "--format",
            "json",
            "--track-mcp-call-sizes",
        )

        assert result.returncode == 0, (
            f"dashboard --track-mcp-call-sizes exited {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )
        usage = json.loads(result.stdout)["by_mcp_usage"]

        assert usage["cost_attribution"] == {
            "method": "tool_result_payload_size",
            "is_proxy": True,
            "unit": "estimated_tokens",
            "basis": "len(tool_result content) / chars_per_token",
            "chars_per_token": 4.0,
            "excludes": ["tool_use.input arguments", "image content blocks"],
            "calls_with_result": 1,
            "calls_without_result": 1,
            "calls_with_excluded_content": 1,
        }

        server_info = usage["by_server"]["proxy-demo"]
        assert server_info["estimated_result_tokens"] == {
            "total": 10.0,
            "mean_result_tokens_per_call": 10.0,
        }
        assert server_info["by_method_tokens"]["measured_call"] == {
            "total": 10.0,
            "mean_result_tokens_per_call": 10.0,
        }
        assert server_info["by_method_tokens"]["image_call"] == {
            "total": 0.0,
            "mean_result_tokens_per_call": None,
        }
        assert server_info["by_method_tokens"]["missing_call"] == {
            "total": 0.0,
            "mean_result_tokens_per_call": None,
        }
