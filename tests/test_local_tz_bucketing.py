"""Tests for issue #197: dashboard day-bucketing uses local timezone.

Covers:
- ``localDateKey`` helper exists in ``cp-utils.js`` and is exported on
  ``window.CP``.
- UTC-slice patterns (``toISOString().slice(0, 10)`` and
  ``s.start_time.slice(0, 10)``) are gone from the client-computed
  local-bucketing surfaces in ``cp-utils.js`` and
  ``views/economics-basic.js``.
- Local-key patterns (``localDateKey``) are used consistently for
  both anchor-day generation and session day-keying in those files.
- ``reAggregate`` and ``modelSeries`` in ``cp-utils.js`` use
  ``localDateKey`` for their day keys.
- ``economics-basic.js`` uses ``localDateKey`` for both anchor and
  session date keys so "today" resolves in local time.
- ``window.CP`` exports the helper so consumers don't need a second
  global.

Note: ``economics.js`` lines ~1047/~1052 read ``window.DATA.by_day``
(Python-aggregated UTC keys) and are deliberately OUT OF SCOPE — the
localised client key must match the UTC anchor in that file, so those
lines are left untouched (see issue #197 decision log).
"""

from __future__ import annotations

from pathlib import Path

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _REPO_ROOT / "src" / "claude_prospector" / "static"
_CP_UTILS = _STATIC / "cp-utils.js"
_ECONOMICS_BASIC = _STATIC / "views" / "economics-basic.js"
_ECONOMICS = _STATIC / "views" / "economics.js"


def _render_html(tmp_path: Path) -> str:
    """Render dashboard HTML and return it as a string.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Rendered HTML string.
    """
    out = tmp_path / "dashboard.html"
    render(AggregateResult(), output_path=out, open_browser=False)
    return out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# RED tests: verify localDateKey helper exists and is exported
# ---------------------------------------------------------------------------


class TestLocalDateKeyHelper:
    """Verify ``localDateKey`` is defined and exported in cp-utils.js."""

    def test_local_date_key_defined_in_cp_utils(self) -> None:
        """cp-utils.js must define a ``localDateKey`` function."""
        content = _CP_UTILS.read_text(encoding="utf-8")
        assert "function localDateKey" in content, (
            "cp-utils.js does not define 'function localDateKey'. "
            "The helper must be added to cp-utils.js for issue #197."
        )

    def test_local_date_key_exported_on_window_cp(self) -> None:
        """cp-utils.js must export ``localDateKey`` on ``window.CP``."""
        content = _CP_UTILS.read_text(encoding="utf-8")
        assert (
            "localDateKey" in content
        ), "cp-utils.js does not reference 'localDateKey' at all."
        # Check it appears in the window.CP export block
        # The export block looks like: window.CP = { ..., localDateKey, ... }
        assert "localDateKey," in content or "localDateKey\n" in content, (
            "localDateKey does not appear in the window.CP export object. "
            "It must be exported so economics-basic.js can use CP.localDateKey."
        )

    def test_local_date_key_present_in_rendered_html(self, tmp_path: Path) -> None:
        """Rendered HTML must contain 'localDateKey' from cp-utils.js."""
        html = _render_html(tmp_path)
        assert "localDateKey" in html, (
            "Rendered HTML does not contain 'localDateKey'. "
            "cp-utils.js is inlined — the helper must be present in the "
            "rendered output."
        )

    def test_local_date_key_uses_local_components(self) -> None:
        """localDateKey must use local-time getters, not toISOString/UTC.

        The helper must compose date components from getFullYear/getMonth/
        getDate (local-time accessors) rather than calling toISOString()
        which always returns a UTC representation.

        We look for the getter inside the localDateKey function body by
        checking that ``getFullYear`` appears AFTER the function definition.
        """
        content = _CP_UTILS.read_text(encoding="utf-8")
        fn_idx = content.find("function localDateKey")
        assert fn_idx != -1, "localDateKey function not found in cp-utils.js."
        after_fn = content[fn_idx:]
        assert "getFullYear" in after_fn or (
            "toLocaleDateString" in after_fn and "en-CA" in after_fn
        ), (
            "localDateKey does not use local-time getters "
            "(getFullYear/getMonth/getDate or toLocaleDateString('en-CA')). "
            "The helper must produce a YYYY-MM-DD key in local time."
        )


# ---------------------------------------------------------------------------
# RED tests: UTC-slice patterns removed from local-bucketing surfaces
# ---------------------------------------------------------------------------


class TestUtcSliceRemovedFromCpUtils:
    """Verify cp-utils.js no longer uses UTC-slice for day bucketing."""

    def test_reaggregate_uses_local_date_key(self) -> None:
        """reAggregate() in cp-utils.js must call localDateKey, not UTC slice.

        Previously: ``s.start_time.slice(0, 10)``
        Required:   ``localDateKey(new Date(s.start_time))``
        """
        content = _CP_UTILS.read_text(encoding="utf-8")
        # Check that the localDateKey call is present in the byDay block
        assert "localDateKey(new Date(s.start_time))" in content, (
            "cp-utils.js reAggregate() must use "
            "localDateKey(new Date(s.start_time)) for day keys, not "
            "s.start_time.slice(0, 10)."
        )

    def test_model_series_uses_local_date_key(self) -> None:
        """modelSeries() in cp-utils.js must use localDateKey for anchor keys.

        Previously: ``d.toISOString().slice(0, 10)``
        Required:   ``localDateKey(d)``
        """
        content = _CP_UTILS.read_text(encoding="utf-8")
        # The modelSeries function uses d.toISOString().slice(0,10) to look up
        # by_day keys; that surface is for client-recomputed byDay, so it
        # must be localized.
        assert "localDateKey(d)" in content, (
            "cp-utils.js modelSeries() must use localDateKey(d) for anchor "
            "keys, not d.toISOString().slice(0, 10)."
        )


class TestUtcSliceRemovedFromEconomicsBasic:
    """Verify economics-basic.js no longer uses UTC-slice for day bucketing."""

    def test_active_days_anchor_uses_local_date_key(self) -> None:
        """Active-days anchor loop must use CP.localDateKey, not UTC slice.

        The loop builds ``recentDateKeys`` for the last 7 calendar days.
        Previously: ``d.toISOString().slice(0, 10)``
        Required:   ``CP.localDateKey(d)``
        """
        content = _ECONOMICS_BASIC.read_text(encoding="utf-8")
        assert "CP.localDateKey(d)" in content, (
            "economics-basic.js must use CP.localDateKey(d) for anchor "
            "day keys (recentDateKeys loop), not d.toISOString().slice(0,10)."
        )

    def test_session_date_key_uses_local_date_key(self) -> None:
        """Session day-key mapping must use CP.localDateKey, not UTC slice.

        Previously: ``s.start_time.slice(0, 10)``
        Required:   ``CP.localDateKey(new Date(s.start_time))``
        """
        content = _ECONOMICS_BASIC.read_text(encoding="utf-8")
        assert "CP.localDateKey(new Date(s.start_time))" in content, (
            "economics-basic.js must use CP.localDateKey(new Date(s.start_time)) "
            "for session day keys, not s.start_time.slice(0, 10)."
        )

    def test_daily_bar_anchor_uses_local_date_key(self) -> None:
        """14-day bar loop anchor must use CP.localDateKey, not UTC slice.

        The loop builds ``daily`` bars for the last 14 days.
        Previously: ``d.toISOString().slice(0, 10)``
        Required:   ``CP.localDateKey(d)``
        """
        content = _ECONOMICS_BASIC.read_text(encoding="utf-8")
        # CP.localDateKey(d) already asserts presence; this test uses a
        # distinct assertion to check usage count — both the anchor and the
        # session filter in the daily loop must use the local helper.
        occurrences = content.count("CP.localDateKey(d)")
        assert occurrences >= 2, (  # noqa: PLR2004
            f"economics-basic.js contains {occurrences} call(s) to "
            "CP.localDateKey(d), expected at least 2 — one for the "
            "active-days loop and one for the daily-bar loop."
        )

    def test_no_utc_start_time_slice_in_economics_basic(self) -> None:
        """economics-basic.js must not use s.start_time.slice(0,10) for buckets.

        After the fix, session day-keying must go through
        CP.localDateKey(new Date(s.start_time)).
        """
        content = _ECONOMICS_BASIC.read_text(encoding="utf-8")
        assert "s.start_time.slice(0, 10)" not in content, (
            "economics-basic.js still contains s.start_time.slice(0, 10). "
            "All session day-keying must use CP.localDateKey(new Date(s.start_time))."
        )


# ---------------------------------------------------------------------------
# Out-of-scope verification: economics.js Python-backed by_day is unchanged
# ---------------------------------------------------------------------------


class TestEconomicsJsOutOfScope:
    """Verify economics.js Python-backed by_day lookup is NOT localized.

    economics.js reads window.DATA.by_day (Python-generated UTC keys) and
    anchors its loop with toISOString().slice(0,10) to match those UTC keys.
    Per the issue #197 decision, this surface is out of scope — localizing
    the anchor without also localizing Python's by_day keys would mismatch.
    """

    def test_economics_js_still_has_utc_anchor_for_by_day(self) -> None:
        """economics.js must still use toISOString().slice(0,10) for by_day.

        This is intentional — do NOT change this surface.  A follow-up issue
        (#197 decision log) will handle Python-side by_day localization if
        desired.
        """
        content = _ECONOMICS.read_text(encoding="utf-8")
        assert "toISOString().slice(0, 10)" in content, (
            "economics.js no longer contains toISOString().slice(0, 10). "
            "This surface is intentionally out-of-scope for #197 — the "
            "by_day anchor must match Python's UTC-keyed aggregator output. "
            "If you localized this, revert it."
        )
