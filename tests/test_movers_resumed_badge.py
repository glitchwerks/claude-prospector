"""Tests for issue #200: Movers tab must distinguish "resumed" from "new".

An agent/project that was active more than 14 days ago, idle in the 7-14 day
prior window, and active again in the last 7 days must show "resumed" — not
"new" — in the Movers tab.

Coverage level: source-level assertions on ``layout-b-diag.js`` plus a
rendered-HTML assertion confirming both labels appear in the inlined output.
The JS does not run under pytest, so we cannot execute the functions; instead
we verify:

1. ``computeMovers``'s ``dlt`` accepts a ``hasHistory`` parameter and returns
   sentinel 998 when the entity has prior history (``resumed``) vs. 999 when
   it has no prior history (``new``).
2. The ``biggestUp`` filter excludes **both** sentinels (``< 998``), not just
   ``< 999``.
3. ``tabMovers``'s own ``dlt`` closure renders "resumed" for delta 998 and
   "new" for delta 999.
4. ``window.DATA.by_project`` is accessed in ``computeMovers`` to determine
   all-time history for projects.
5. ``window.DATA.by_agent`` is accessed in ``computeMovers`` to determine
   all-time history for agents (already present, but coverage of the new
   ``hasHistory`` lookup).
6. Rendered HTML contains the string ``resumed`` (confirming the label ships
   in the inlined JavaScript).
"""

from __future__ import annotations

from pathlib import Path

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LAYOUT_B_DIAG = (
    _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "layout-b-diag.js"
)


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
# computeMovers — dlt() signature (hasHistory parameter)
# ---------------------------------------------------------------------------


class TestComputeMoversDltSignature:
    """``dlt`` in ``computeMovers`` must accept a ``hasHistory`` parameter."""

    def test_compute_movers_dlt_accepts_has_history(self) -> None:
        """computeMovers' dlt must take three arguments including hasHistory.

        The new signature is ``dlt(cur, pre, hasHistory)`` so that it can
        return 998 (resumed) vs 999 (genuinely new) when ``pre === 0``.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "dlt(cur, pre, hasHistory)" in content, (
            "computeMovers' dlt does not have a 'hasHistory' parameter. "
            "The function signature must be 'dlt(cur, pre, hasHistory)' "
            "to distinguish resumed from genuinely new entities (issue #200)."
        )

    def test_compute_movers_dlt_returns_998_for_resumed(self) -> None:
        """computeMovers' dlt must return 998 when hasHistory is truthy.

        When pre === 0 and hasHistory is true, the entity has prior history
        outside the prior-7-day window — it should be "resumed" (998), not
        "new" (999).
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "hasHistory ? 998 : 999" in content, (
            "computeMovers' dlt does not use 'hasHistory ? 998 : 999'. "
            "The ternary must return 998 for resumed entities and 999 for "
            "genuinely new ones (issue #200)."
        )

    def test_compute_movers_dlt_comment_explains_sentinels(self) -> None:
        """computeMovers must have a comment explaining sentinel values.

        A comment ``// 999 = genuinely new`` or similar should appear near
        the dlt definition to document the sentinel contract.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "999" in content and "genuinely new" in content, (
            "layout-b-diag.js does not contain a comment explaining the 999 "
            "sentinel as 'genuinely new'. Add a comment near computeMovers' "
            "dlt definition (issue #200)."
        )


# ---------------------------------------------------------------------------
# computeMovers — hasHistory lookup for agents and projects
# ---------------------------------------------------------------------------


class TestComputeMoversHasHistoryLookup:
    """computeMovers must look up all-time totals to determine hasHistory."""

    def test_compute_movers_agents_lookup_by_agent_auth(self) -> None:
        """computeMovers must read window.DATA.by_agent for agent history.

        The variable ``auth`` (or similar) must read
        ``window.DATA.by_agent[a]`` and check its total_tokens against ``cur``
        to decide whether the entity has prior history.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "window.DATA.by_agent[a]" in content, (
            "computeMovers does not read 'window.DATA.by_agent[a]' for the "
            "agent all-time total. Add a hasHistory lookup via "
            "'window.DATA.by_agent[a]' (issue #200)."
        )

    def test_compute_movers_projects_lookup_by_project(self) -> None:
        """computeMovers must read window.DATA.by_project for project history.

        A variable must read ``window.DATA.by_project[name]`` and compare
        its total_tokens to the recent window total to set hasHistory.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "window.DATA.by_project[name]" in content, (
            "computeMovers does not read 'window.DATA.by_project[name]' for "
            "project all-time history. The fix must add a hasHistory lookup "
            "for projects using 'window.DATA.by_project[name]' (issue #200)."
        )

    def test_compute_movers_has_history_uses_total_tokens_comparison(
        self,
    ) -> None:
        """computeMovers must compare total_tokens > cur to set hasHistory.

        The logic ``auth.total_tokens > cur`` (or equivalent) determines
        whether an agent/project has prior history outside the recent window.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "total_tokens > cur" in content, (
            "computeMovers does not contain 'total_tokens > cur' to compare "
            "all-time tokens against the recent window total. The hasHistory "
            "check must use this comparison (issue #200)."
        )


# ---------------------------------------------------------------------------
# computeMovers — biggestUp filter excludes BOTH sentinels
# ---------------------------------------------------------------------------


class TestComputeMoversBiggestUpFilter:
    """``biggestUp`` must exclude both 998 and 999 (not just 999)."""

    def test_biggest_up_excludes_sentinel_998(self) -> None:
        """biggestUp filter must use ``a.delta < 998``, not ``< 999``.

        The filter previously used ``< 999`` which still included "resumed"
        (998) entities in the biggest-up slot. After the fix it must use
        ``< 998`` so both sentinels are excluded.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "a.delta < 998" in content, (
            "biggestUp filter still uses '< 999' instead of '< 998'. "
            "Both sentinels (998 = resumed, 999 = new) must be excluded from "
            "biggestUp to avoid misleading percentage slots (issue #200)."
        )

    def test_biggest_up_projects_filter_excludes_sentinel_998(self) -> None:
        """biggestUp project-side filter must also use ``< 998``.

        The concat'd project filter must use the same threshold as the agent
        filter.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        # Both sides must filter with < 998; count occurrences
        occurrences = content.count("delta < 998")
        assert occurrences >= 2, (
            f"Expected at least 2 occurrences of 'delta < 998' (agent and "
            f"project sides of biggestUp), found {occurrences}. Both sides "
            "must exclude both sentinels (issue #200)."
        )


# ---------------------------------------------------------------------------
# tabMovers — its own dlt closure handles 998 -> "resumed"
# ---------------------------------------------------------------------------


class TestTabMoversDltClosure:
    """``tabMovers``'s ``dlt`` closure must render 'resumed' for delta 998."""

    def test_tab_movers_dlt_renders_resumed_label(self) -> None:
        """tabMovers' dlt must emit 'resumed' text for delta value 998.

        The closure must include a branch ``d === 998 ? 'resumed'`` (or
        equivalent) to render the badge text.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "'resumed'" in content or '"resumed"' in content, (
            "layout-b-diag.js does not contain the string 'resumed'. "
            "tabMovers' dlt closure must render 'resumed' for delta 998 "
            "(issue #200)."
        )

    def test_tab_movers_dlt_handles_sentinel_698_in_class(self) -> None:
        """tabMovers' dlt cls branch must use >= 998 for the 'up' class.

        When d >= 998 (either 998 or 999), the delta badge should use the
        'up' CSS class. The class condition must be ``d >= 998``.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "d >= 998" in content, (
            "tabMovers' dlt closure does not contain 'd >= 998' for the CSS "
            "class. Both sentinels (998 and 999) should render with the 'up' "
            "class (issue #200)."
        )

    def test_tab_movers_dlt_still_renders_new_for_999(self) -> None:
        """tabMovers' dlt must still render 'new' for delta 999.

        The 'new' label must be preserved for genuinely new entities.
        The condition ``d >= 999 ? 'new'`` (or equivalent) must still exist.
        """
        content = _LAYOUT_B_DIAG.read_text(encoding="utf-8")
        assert "d >= 999" in content or "d === 999" in content, (
            "tabMovers' dlt closure no longer contains a condition for "
            "delta 999 ('new'). Both 'new' and 'resumed' labels must be "
            "present (issue #200)."
        )


# ---------------------------------------------------------------------------
# Rendered HTML — "resumed" label ships in inlined output
# ---------------------------------------------------------------------------


class TestRenderedHtmlContainsResumedLabel:
    """The rendered HTML must contain the string 'resumed'."""

    def test_rendered_html_contains_resumed(self, tmp_path: Path) -> None:
        """Rendered dashboard HTML must include the 'resumed' badge label.

        layout-b-diag.js is inlined into the HTML. The presence of 'resumed'
        in the rendered output confirms the JS source shipped the new label.
        """
        html = _render_html(tmp_path)
        assert "resumed" in html, (
            "Rendered dashboard HTML does not contain 'resumed'. "
            "layout-b-diag.js must be updated so tabMovers' dlt closure "
            "emits this label for delta 998 (issue #200)."
        )

    def test_rendered_html_still_contains_new(self, tmp_path: Path) -> None:
        """Rendered dashboard HTML must still include the 'new' label text.

        The 'new' sentinel (999) for genuinely new entities must be preserved.
        """
        html = _render_html(tmp_path)
        # 'new' must appear as part of the JS source strings in the HTML
        assert "'new'" in html or '"new"' in html, (
            "Rendered dashboard HTML does not contain the string 'new' as a "
            "quoted JS literal. The 'new' label for genuinely-new entities "
            "must be preserved alongside the 'resumed' label (issue #200)."
        )
