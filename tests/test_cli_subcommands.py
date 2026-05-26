"""Tests for top-level CLI subparser routing."""

from __future__ import annotations

import argparse
import subprocess
import sys

import pytest

from claude_prospector.cli.dashboard import build_parser


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run claude_prospector as a module and capture output.

    Args:
        *args: Command-line arguments to pass after the module name.

    Returns:
        CompletedProcess with stdout, stderr, and returncode populated.
    """
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", *args],
        capture_output=True,
        text=True,
    )


def test_bare_invocation_exits_0_and_shows_subcommands() -> None:
    """Bare 'claude-prospector' with no args must exit 0 and list subcommands."""
    result = _run()
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "dashboard" in combined
    assert "session-summary" in combined


def test_dashboard_help_exits_0() -> None:
    """'claude-prospector dashboard --help' must exit 0."""
    result = _run("dashboard", "--help")
    assert result.returncode == 0


def test_old_flag_only_form_exits_nonzero() -> None:
    """'claude-prospector --format json' (old form) must exit non-zero post-refactor.

    The top-level parser no longer accepts --format; callers must migrate
    to 'claude-prospector dashboard --format json'.
    """
    result = _run("--format", "json")
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Issue #188 — dashboard subcommand must NOT default --window to 7d
# ---------------------------------------------------------------------------


def test_dashboard_no_window_flag_yields_none() -> None:
    """Invoking 'dashboard' with no --window flag must parse window as None.

    Previously the dashboard subcommand defaulted to 7d, causing the
    aggregator to drop prior-period data needed for week-over-week
    comparison panes (issue #188). The default must be None (no filter).
    """
    top = argparse.ArgumentParser()
    sub = top.add_subparsers()
    build_parser(sub)
    args = top.parse_args(["dashboard"])
    assert args.window is None, (
        f"Expected args.window to be None when --window is omitted, "
        f"got {args.window!r}. "
        f"The dashboard subcommand must not default --window to any value "
        f"(issue #188)."
    )


def test_dashboard_explicit_window_flag_still_works() -> None:
    """Passing '--window 7d' must still set args.window (opt-in preserved)."""
    top = argparse.ArgumentParser()
    sub = top.add_subparsers()
    build_parser(sub)
    args = top.parse_args(["dashboard", "--window", "7d"])
    # 7d = 168 hours
    assert args.window == pytest.approx(168.0), (
        f"Expected args.window == 168.0 when --window 7d is passed, "
        f"got {args.window!r}."
    )
