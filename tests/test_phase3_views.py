"""Tests for Phase 3 (issue #168): three view renderers + wiring.

Covers:
- All three view JS files exist on disk under
  ``src/claude_prospector/static/views/``.
- ``importlib.resources.files("claude_prospector.static.views")`` can
  read each one and the content is non-empty.
- Rendered ``dashboard.html`` (via ``renderer.py``) contains the three
  function names confirming wiring is present.
- Subtitles per tab match the spec verbatim.
- Overview "Switch to Advanced" CTA dispatches the correct event.
- Phase 3 placeholder tests from Phase 2 now resolve to actual content.
- Smoke test: renderer runs against fixture data with no Python errors.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATIC_VIEWS = _REPO_ROOT / "src" / "claude_prospector" / "static" / "views"


def _render_html(tmp_path: Path, result: AggregateResult | None = None) -> str:
    """Render dashboard HTML and return it as a string.

    Args:
        tmp_path: Pytest temporary directory.
        result: Optional aggregate result; defaults to empty AggregateResult.

    Returns:
        Rendered HTML string.
    """
    if result is None:
        result = AggregateResult()
    out = tmp_path / "dashboard.html"
    render(result, output_path=out, open_browser=False)
    return out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# View files exist on disk
# ---------------------------------------------------------------------------


class TestViewFilesOnDisk:
    """Verify all three view JS files exist under static/views/."""

    def test_economics_basic_exists(self) -> None:
        """economics-basic.js must exist under static/views/."""
        p = _STATIC_VIEWS / "economics-basic.js"
        assert p.is_file(), f"Missing: {p}"

    def test_layout_b_diag_exists(self) -> None:
        """layout-b-diag.js must exist under static/views/."""
        p = _STATIC_VIEWS / "layout-b-diag.js"
        assert p.is_file(), f"Missing: {p}"

    def test_economics_exists(self) -> None:
        """economics.js must exist under static/views/."""
        p = _STATIC_VIEWS / "economics.js"
        assert p.is_file(), f"Missing: {p}"

    def test_economics_basic_non_empty(self) -> None:
        """economics-basic.js must be non-trivially large (>5 KB)."""
        p = _STATIC_VIEWS / "economics-basic.js"
        assert (
            p.stat().st_size >= 5_000
        ), f"economics-basic.js is suspiciously small: {p.stat().st_size} bytes"

    def test_layout_b_diag_non_empty(self) -> None:
        """layout-b-diag.js must be non-trivially large (>20 KB)."""
        p = _STATIC_VIEWS / "layout-b-diag.js"
        assert (
            p.stat().st_size >= 20_000
        ), f"layout-b-diag.js is suspiciously small: {p.stat().st_size} bytes"

    def test_economics_non_empty(self) -> None:
        """economics.js must be non-trivially large (>15 KB)."""
        p = _STATIC_VIEWS / "economics.js"
        assert (
            p.stat().st_size >= 15_000
        ), f"economics.js is suspiciously small: {p.stat().st_size} bytes"


# ---------------------------------------------------------------------------
# importlib.resources accessibility
# ---------------------------------------------------------------------------


class TestViewFilesImportlibResources:
    """Verify view files are accessible via importlib.resources.

    This proves the assets will be reachable in wheel installs, not just
    the editable source tree.
    """

    def test_economics_basic_accessible(self) -> None:
        """importlib.resources can locate static/views/economics-basic.js."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "views" / "economics-basic.js"
        assert asset.is_file(), (
            "static/views/economics-basic.js is not accessible via "
            "importlib.resources — check pyproject.toml package-data."
        )

    def test_layout_b_diag_accessible(self) -> None:
        """importlib.resources can locate static/views/layout-b-diag.js."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "views" / "layout-b-diag.js"
        assert asset.is_file(), (
            "static/views/layout-b-diag.js is not accessible via "
            "importlib.resources — check pyproject.toml package-data."
        )

    def test_economics_accessible(self) -> None:
        """importlib.resources can locate static/views/economics.js."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "views" / "economics.js"
        assert asset.is_file(), (
            "static/views/economics.js is not accessible via "
            "importlib.resources — check pyproject.toml package-data."
        )

    def test_economics_basic_content_non_empty(self) -> None:
        """economics-basic.js content must be non-empty via importlib."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "views" / "economics-basic.js"
        content = asset.read_text(encoding="utf-8")
        assert content.strip(), "economics-basic.js has no content."

    def test_layout_b_diag_content_non_empty(self) -> None:
        """layout-b-diag.js content must be non-empty via importlib."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "views" / "layout-b-diag.js"
        content = asset.read_text(encoding="utf-8")
        assert content.strip(), "layout-b-diag.js has no content."

    def test_economics_content_non_empty(self) -> None:
        """economics.js content must be non-empty via importlib."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "views" / "economics.js"
        content = asset.read_text(encoding="utf-8")
        assert content.strip(), "economics.js has no content."


# ---------------------------------------------------------------------------
# Rendered HTML: function names confirm wiring
# ---------------------------------------------------------------------------


class TestRenderedHtmlFunctionNames:
    """Verify rendered HTML contains the three renderer function names."""

    def test_render_economics_basic_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain 'renderEconomicsBasic'."""
        html = _render_html(tmp_path)
        assert "renderEconomicsBasic" in html, (
            "Rendered HTML does not contain 'renderEconomicsBasic'. "
            "economics-basic.js is not wired in."
        )

    def test_render_layout_b_diag_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain 'renderLayoutBDiag'."""
        html = _render_html(tmp_path)
        assert "renderLayoutBDiag" in html, (
            "Rendered HTML does not contain 'renderLayoutBDiag'. "
            "layout-b-diag.js is not wired in."
        )

    def test_render_economics_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain 'renderEconomics'."""
        html = _render_html(tmp_path)
        assert "renderEconomics" in html, (
            "Rendered HTML does not contain 'renderEconomics'. "
            "economics.js is not wired in."
        )


# ---------------------------------------------------------------------------
# Rendered HTML: tab subtitles match spec verbatim
# ---------------------------------------------------------------------------


class TestTabSubtitles:
    """Verify the subtitles for each tab match spec verbatim."""

    def test_overview_subtitle_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the Overview subtitle verbatim."""
        html = _render_html(tmp_path)
        subtitle = "A weekly snapshot of how much you're using Claude Code."
        assert subtitle in html, (
            f"Overview subtitle not found verbatim. " f"Expected: {subtitle!r}"
        )

    def test_breakdown_subtitle_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the Breakdown subtitle verbatim."""
        html = _render_html(tmp_path)
        subtitle = (
            "Where your tokens go — projects, agents, "
            "skills and adoption, full session log."
        )
        assert subtitle in html, (
            f"Breakdown subtitle not found verbatim. " f"Expected: {subtitle!r}"
        )

    def test_advanced_subtitle_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the Advanced subtitle."""
        html = _render_html(tmp_path)
        # The Advanced subtitle contains partial text; check the key phrase.
        assert (
            "Per-turn cost lever metrics" in html
        ), "Advanced subtitle ('Per-turn cost lever metrics') not found. "


# ---------------------------------------------------------------------------
# Rendered HTML: "Switch to Advanced" CTA
# ---------------------------------------------------------------------------


class TestSwitchToAdvancedCta:
    """Verify the Overview CTA dispatches economy:switch-view to advanced."""

    def test_switch_view_advanced_cta_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the 'Switch to Advanced' CTA trigger."""
        html = _render_html(tmp_path)
        # The CTA dispatches economy:switch-view with view: 'advanced'
        assert "economy:switch-view" in html, (
            "Rendered HTML does not contain 'economy:switch-view'. "
            "The CTA wiring is absent."
        )

    def test_switch_to_advanced_event_detail(self, tmp_path: Path) -> None:
        """Rendered HTML must contain a dispatch with view: 'advanced'."""
        html = _render_html(tmp_path)
        # economics-basic.js dispatches view: 'advanced'
        assert "'advanced'" in html or '"advanced"' in html, (
            "Rendered HTML does not contain a reference to the 'advanced' view. "
            "The 'Switch to Advanced' CTA wiring may be absent."
        )


# ---------------------------------------------------------------------------
# Rendered HTML: Phase 3 placeholder is now gone (real renderers in place)
# ---------------------------------------------------------------------------


class TestPhase3PlaceholderGone:
    """Verify Phase 3 placeholder content is replaced by real renderer calls.

    Phase 2 added placeholder cards for Breakdown and Advanced.
    Phase 3 removes them and wires real renderers instead.
    """

    def test_no_phase3_placeholder_in_shell_script(self, tmp_path: Path) -> None:
        """The shell JS must no longer call _renderPlaceholder for tabs."""
        html = _render_html(tmp_path)
        # The Phase 2 shell called _renderPlaceholder for Breakdown/Advanced.
        # Phase 3 replaces these calls with the real renderer calls.
        assert "_renderPlaceholder" not in html, (
            "Rendered HTML still contains '_renderPlaceholder'. "
            "Phase 3 renderers must replace Phase 2 placeholder calls."
        )


# ---------------------------------------------------------------------------
# Renderer smoke test with fixture data
# ---------------------------------------------------------------------------


class TestRendererSmoke:
    """Verify the dashboard renderer runs against fixture data without errors."""

    def test_render_with_empty_data(self, tmp_path: Path) -> None:
        """Renderer must not raise with an empty AggregateResult."""
        result = AggregateResult()
        out = tmp_path / "dashboard_empty.html"
        render(result, output_path=out, open_browser=False)
        html = out.read_text(encoding="utf-8")
        assert len(html) > 1000, "Rendered HTML is suspiciously short."

    def test_render_with_session_data(self, tmp_path: Path) -> None:
        """Renderer must not raise with populated session data.

        Exercises the per-token-type fields from aggregator #165 to
        confirm no key-error or rendering failure occurs Python-side.
        """
        result = AggregateResult(
            total_tokens=50_000,
            total_messages=100,
            total_sessions=3,
            by_day={
                "2026-05-20": {
                    "total_tokens": 15_000,
                    "input_tokens": 5_000,
                    "output_tokens": 3_000,
                    "cache_creation_tokens": 4_000,
                    "cache_read_tokens": 3_000,
                    "message_count": 30,
                    "by_model": {"sonnet": 15_000},
                },
                "2026-05-21": {
                    "total_tokens": 35_000,
                    "input_tokens": 10_000,
                    "output_tokens": 8_000,
                    "cache_creation_tokens": 12_000,
                    "cache_read_tokens": 5_000,
                    "message_count": 70,
                    "by_model": {"sonnet": 35_000},
                },
            },
            sessions=[
                {
                    "session_id": "abc123",
                    "project": "my-project",
                    "start_time": "2026-05-21T10:00:00+00:00",
                    "root_agent": "general",
                    "agents": ["general"],
                    "total_tokens": 35_000,
                    "input_tokens": 10_000,
                    "output_tokens": 8_000,
                    "cache_creation_tokens": 12_000,
                    "cache_read_tokens": 5_000,
                    "model_split": {"sonnet": 35_000},
                    "duration_minutes": 45.0,
                    "message_count": 70,
                }
            ],
        )
        out = tmp_path / "dashboard_session.html"
        render(result, output_path=out, open_browser=False)
        html = out.read_text(encoding="utf-8")
        assert "my-project" in html, (
            "Rendered HTML does not contain the session's project name. "
            "Data injection may be broken."
        )
        # Confirm per-token-type fields are in the JSON payload
        assert "cache_creation_tokens" in html, (
            "Rendered HTML does not contain 'cache_creation_tokens'. "
            "Per-token-type fields from aggregator #165 must be included."
        )
        assert "input_tokens" in html, (
            "Rendered HTML does not contain 'input_tokens'. "
            "Per-token-type fields from aggregator #165 must be included."
        )
