"""Tests for Phase 2 (issue #167): Economy v1 shell + vendor assets.

Covers:
- Static assets are present under src/claude_prospector/static/
- Static assets are accessible via importlib.resources
- Rendered dashboard HTML contains the three-tab segmented control
- Dark theme colours are present in the rendered HTML
- ``economy:switch-view`` event handler is present in the rendered HTML
- ``window.DATA`` is populated (no MOCK_DATA references)
- Chart.js and treemap JS are inlined in rendered output
- pyproject.toml [tool.setuptools.package-data] covers static/**/*
"""

from __future__ import annotations

import importlib.resources
import tomllib
from pathlib import Path

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


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
# Static asset presence on disk
# ---------------------------------------------------------------------------


class TestStaticAssetFiles:
    """Verify static assets exist on disk under the package source tree."""

    def test_vendor_chart_js_exists(self) -> None:
        """chart.umd.min.js must exist under static/vendor/."""
        p = (
            _REPO_ROOT
            / "src"
            / "claude_prospector"
            / "static"
            / "vendor"
            / "chart.umd.min.js"
        )
        assert p.is_file(), f"Missing: {p}"

    def test_vendor_treemap_js_exists(self) -> None:
        """chartjs-chart-treemap.min.js must exist under static/vendor/."""
        p = (
            _REPO_ROOT
            / "src"
            / "claude_prospector"
            / "static"
            / "vendor"
            / "chartjs-chart-treemap.min.js"
        )
        assert p.is_file(), f"Missing: {p}"

    def test_cp_utils_js_exists(self) -> None:
        """cp-utils.js must exist under static/."""
        p = _REPO_ROOT / "src" / "claude_prospector" / "static" / "cp-utils.js"
        assert p.is_file(), f"Missing: {p}"

    def test_chart_js_non_empty(self) -> None:
        """chart.umd.min.js must be non-trivially large (Chart.js 4 is ~200 KB)."""
        p = (
            _REPO_ROOT
            / "src"
            / "claude_prospector"
            / "static"
            / "vendor"
            / "chart.umd.min.js"
        )
        assert (
            p.stat().st_size >= 100_000
        ), f"chart.umd.min.js is suspiciously small: {p.stat().st_size} bytes"

    def test_treemap_js_non_empty(self) -> None:
        """chartjs-chart-treemap.min.js must be non-trivially large (>10 KB)."""
        p = (
            _REPO_ROOT
            / "src"
            / "claude_prospector"
            / "static"
            / "vendor"
            / "chartjs-chart-treemap.min.js"
        )
        assert p.stat().st_size >= 10_000, (
            f"chartjs-chart-treemap.min.js is suspiciously small: "
            f"{p.stat().st_size} bytes"
        )

    def test_cp_utils_js_non_empty(self) -> None:
        """cp-utils.js must be non-trivially large (>8 KB)."""
        p = _REPO_ROOT / "src" / "claude_prospector" / "static" / "cp-utils.js"
        assert (
            p.stat().st_size >= 8_000
        ), f"cp-utils.js is suspiciously small: {p.stat().st_size} bytes"


# ---------------------------------------------------------------------------
# importlib.resources accessibility
# ---------------------------------------------------------------------------


class TestStaticAssetImportlibResources:
    """Verify static assets are accessible via importlib.resources.

    This proves the assets will be reachable in wheel installs, not just
    the editable source tree.
    """

    def test_chart_js_accessible(self) -> None:
        """importlib.resources can locate static/vendor/chart.umd.min.js."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "vendor" / "chart.umd.min.js"
        assert asset.is_file(), (
            "static/vendor/chart.umd.min.js is not accessible via "
            "importlib.resources — check pyproject.toml package-data."
        )

    def test_treemap_js_accessible(self) -> None:
        """importlib.resources can locate static/vendor/chartjs-chart-treemap.min.js."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "vendor" / "chartjs-chart-treemap.min.js"
        assert asset.is_file(), (
            "static/vendor/chartjs-chart-treemap.min.js is not accessible via "
            "importlib.resources — check pyproject.toml package-data."
        )

    def test_cp_utils_accessible(self) -> None:
        """importlib.resources can locate static/cp-utils.js."""
        pkg = importlib.resources.files("claude_prospector")
        asset = pkg / "static" / "cp-utils.js"
        assert asset.is_file(), (
            "static/cp-utils.js is not accessible via "
            "importlib.resources — check pyproject.toml package-data."
        )


# ---------------------------------------------------------------------------
# pyproject.toml package-data
# ---------------------------------------------------------------------------


class TestPackageData:
    """Verify pyproject.toml declares static/**/* in package-data."""

    def test_pyproject_static_glob_present(self) -> None:
        """pyproject.toml [tool.setuptools.package-data] must cover static/**/*."""
        with open(_PYPROJECT, "rb") as fh:
            config = tomllib.load(fh)

        pkg_data = (
            config.get("tool", {})
            .get("setuptools", {})
            .get("package-data", {})
            .get("claude_prospector", [])
        )

        # Accept any glob pattern that covers static subpaths
        covers_static = any("static" in entry for entry in pkg_data)
        assert covers_static, (
            f"[tool.setuptools.package-data].claude_prospector does not contain "
            f"a 'static' glob. Current entries: {pkg_data}"
        )


# ---------------------------------------------------------------------------
# Rendered HTML: three-tab segmented control
# ---------------------------------------------------------------------------


class TestThreeTabSegmentedControl:
    """Verify the rendered dashboard HTML has the three-tab view toggle."""

    def test_overview_tab_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain an 'Overview' tab button."""
        html = _render_html(tmp_path)
        assert "Overview" in html, "Rendered HTML does not contain an 'Overview' tab."

    def test_breakdown_tab_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain a 'Breakdown' tab button."""
        html = _render_html(tmp_path)
        assert "Breakdown" in html, "Rendered HTML does not contain a 'Breakdown' tab."

    def test_advanced_tab_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain an 'Advanced' tab button."""
        html = _render_html(tmp_path)
        assert "Advanced" in html, "Rendered HTML does not contain an 'Advanced' tab."

    def test_view_toggle_element_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the view-toggle container element."""
        html = _render_html(tmp_path)
        assert (
            "view-toggle" in html
        ), "Rendered HTML does not contain a 'view-toggle' element."

    def test_view_container_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the view-container div."""
        html = _render_html(tmp_path)
        assert (
            "view-container" in html
        ), "Rendered HTML does not contain a 'view-container' element."

    def test_data_view_attributes_present(self, tmp_path: Path) -> None:
        """Rendered HTML must have data-view attributes for tab switching."""
        html = _render_html(tmp_path)
        assert (
            'data-view="basic"' in html or "data-view='basic'" in html
        ), "Rendered HTML does not have data-view='basic' attribute."


# ---------------------------------------------------------------------------
# Rendered HTML: dark theme colours
# ---------------------------------------------------------------------------


class TestDarkThemeColors:
    """Verify the rendered dashboard uses the Economy v1 dark theme."""

    def test_dark_background_color(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the #0d1117 dark background colour."""
        html = _render_html(tmp_path)
        assert (
            "#0d1117" in html
        ), "Rendered HTML does not contain the dark background colour #0d1117."

    def test_foreground_color(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the #c9d1d9 foreground colour."""
        html = _render_html(tmp_path)
        assert (
            "#c9d1d9" in html
        ), "Rendered HTML does not contain foreground colour #c9d1d9."

    def test_accent_color(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the #d2a8ff accent colour."""
        html = _render_html(tmp_path)
        assert (
            "#d2a8ff" in html
        ), "Rendered HTML does not contain accent colour #d2a8ff."


# ---------------------------------------------------------------------------
# Rendered HTML: event wiring
# ---------------------------------------------------------------------------


class TestEconomySwitchViewEvent:
    """Verify economy:switch-view event handler is present in rendered HTML."""

    def test_switch_view_event_handler_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the economy:switch-view event handler."""
        html = _render_html(tmp_path)
        assert "economy:switch-view" in html, (
            "Rendered HTML does not contain the 'economy:switch-view' "
            "custom event handler."
        )

    def test_set_view_function_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain the setView function for tab switching."""
        html = _render_html(tmp_path)
        assert "setView" in html, (
            "Rendered HTML does not contain the setView function "
            "for switching between tabs."
        )


# ---------------------------------------------------------------------------
# Rendered HTML: window.DATA and no MOCK_DATA
# ---------------------------------------------------------------------------


class TestWindowData:
    """Verify window.DATA is used and MOCK_DATA is absent."""

    def test_window_data_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain 'window.DATA =' for data injection."""
        html = _render_html(tmp_path)
        assert "window.DATA" in html, (
            "Rendered HTML does not contain 'window.DATA'. "
            "Data must be injected via window.DATA from the aggregator."
        )

    def test_no_mock_data_reference(self, tmp_path: Path) -> None:
        """Rendered HTML must NOT contain 'MOCK_DATA'."""
        html = _render_html(tmp_path)
        assert "MOCK_DATA" not in html, (
            "Rendered HTML contains 'MOCK_DATA'. "
            "The template must use window.DATA, not mock data."
        )


# ---------------------------------------------------------------------------
# Rendered HTML: vendor JS inlined
# ---------------------------------------------------------------------------


class TestVendorJsInlined:
    """Verify Chart.js and treemap are inlined in the rendered HTML."""

    def test_chartjs_content_inlined(self, tmp_path: Path) -> None:
        """Rendered HTML must contain Chart.js 4 content (inlined)."""
        html = _render_html(tmp_path)
        # Chart.js v4 UMD bundle contains this copyright header
        assert "Chart.js" in html, (
            "Rendered HTML does not appear to contain Chart.js content. "
            "chart.umd.min.js should be inlined via the renderer."
        )

    def test_treemap_content_inlined(self, tmp_path: Path) -> None:
        """Rendered HTML must contain chartjs-chart-treemap content (inlined)."""
        html = _render_html(tmp_path)
        # chartjs-chart-treemap contains this identifier
        assert "chartjs-chart-treemap" in html or "TreemapController" in html, (
            "Rendered HTML does not appear to contain chartjs-chart-treemap. "
            "chartjs-chart-treemap.min.js should be inlined via the renderer."
        )

    def test_cp_utils_content_inlined(self, tmp_path: Path) -> None:
        """Rendered HTML must contain window.CP from cp-utils.js (inlined)."""
        html = _render_html(tmp_path)
        assert "window.CP" in html, (
            "Rendered HTML does not contain window.CP. "
            "cp-utils.js should be inlined via the renderer."
        )


# ---------------------------------------------------------------------------
# Rendered HTML: Phase 3 placeholders
# ---------------------------------------------------------------------------


class TestPhase3Placeholders:
    """Verify Breakdown and Advanced tabs have placeholder content."""

    def test_phase3_placeholder_present(self, tmp_path: Path) -> None:
        """Breakdown or Advanced tab content must show a Phase 3 placeholder."""
        html = _render_html(tmp_path)
        # Accept 'Phase 3' or 'coming' as placeholder signal
        has_placeholder = "Phase 3" in html or "coming" in html.lower()
        assert has_placeholder, (
            "Rendered HTML does not contain a Phase 3 placeholder for "
            "Breakdown/Advanced tabs."
        )


# ---------------------------------------------------------------------------
# JSON payload shape unchanged (regression)
# ---------------------------------------------------------------------------


class TestJsonPayloadUnchanged:
    """Verify the dashboard --format json payload shape is unchanged."""

    def test_json_output_has_expected_top_level_keys(self) -> None:
        """dashboard --format json must have the same top-level keys as before.

        Phase 2 is template-only — no Python-side data contract changes.
        """
        import json
        import subprocess
        import sys

        fixture_dir = (
            _REPO_ROOT
            / "tests"
            / "fixtures"
            / "session_summaries"
            / "dashboard_baseline_input"
        )

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
                str(fixture_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"dashboard --format json exited {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )

        payload = json.loads(result.stdout)
        expected_keys = {
            "generated_at",
            "total_tokens",
            "total_messages",
            "total_sessions",
            "by_model",
            "by_agent",
            "by_skill",
            "by_project",
            "by_day",
            "sessions",
            "limits",
        }
        actual_keys = set(payload.keys())
        assert actual_keys == expected_keys, (
            f"JSON payload keys changed. "
            f"Expected: {sorted(expected_keys)}, "
            f"Got: {sorted(actual_keys)}"
        )
