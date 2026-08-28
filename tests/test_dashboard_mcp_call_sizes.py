"""Tests for the ``--track-mcp-call-sizes`` CLI flag (issue #262, D-4).

D-4's "yes-isolated-with-secondary-flag" resolution requires the
result-payload-length read to be gated behind a **new**, separate CLI flag
on ``dashboard`` -- distinct from the existing ``--track-mcp-calls`` flag,
which must keep behaving exactly as it does today (call-counts only).

Covers only flag parsing (``build_parser`` in ``cli/dashboard.py``); the
collection-level gating behavior (result_chars staying None until this flag
opts in) is covered by
``tests/unit/test_tool_collection.py::TestCollectToolUsesResultSizes``.
"""

from __future__ import annotations

import argparse

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
