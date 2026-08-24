"""Tests for Phase 2 of the MCP tool-usage dashboard panel (issue #248).

Pins the Phase 2 (view-layer) contract for issue #248 (implemented in
PR #261) before any of it is implemented:

- ``static/views/mcp-usage.js`` exists and exposes ``renderMcpUsage`` in the
  established view-file convention (``economics.js`` etc).
- A new ``data-view="mcp"`` tab button is wired into ``dashboard.html``
  (D-D=(a) — a new top-level view/tab, not embedded in Breakdown).
- The D-E empty state: the tab renders (does not raise, still exposes its
  ``data-view="mcp"`` hook) even when ``by_mcp_usage`` is ``{}``.
- The populated path: a non-empty ``by_mcp_usage`` payload passed to
  ``render()`` reaches the client via the embedded ``window.DATA`` JSON.

Test names carry the plan's T-numbers (§6) so failures trace back to the
requirement they pin. T9 and T12 are **source-containment** assertions, not
rendering assertions — this repo has no JS execution capability (no
``package.json``, no jsdom/playwright in CI; see the plan's "What CAN and
CANNOT be tested automatically" note). They prove the branching code exists
in ``mcp-usage.js``'s source; they do NOT prove it renders correctly in a
browser. Correct rendering of F6 (null-vs-zero) and F9 (skipped-sessions
banner) is a required, blocking **manual** Phase 2 exit gate, not an
automated one. T11 (view resource resolution) lives in
``tests/test_phase3_views.py`` alongside the other view files, not here.
"""

from __future__ import annotations

import re
from pathlib import Path

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_USAGE_JS = (
    _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "mcp-usage.js"
)

# The exact §4.3 by_mcp_usage payload shape (Phase 1's shipped contract),
# used as the "populated" fixture below. One server has real usage, one is
# dormant (sessions_seen_in / avg_calls_per_active_session are null, not 0)
# so F6's null-vs-zero distinction has fixture data to exercise.
_POPULATED_USAGE = {
    "by_tool": {"mcp__demo-server__do_thing": 3},
    "by_server": {
        "demo-server": {
            "total_calls": 3,
            "sessions_seen_in": 2,
            "sessions_used_in": 1,
            "avg_calls_per_active_session": 3.0,
            "by_method": {"do_thing": 3},
        },
        "dormant-server": {
            "total_calls": 0,
            "sessions_seen_in": None,
            "sessions_used_in": 0,
            "avg_calls_per_active_session": None,
            "by_method": {},
        },
    },
    "availability_signal": {},
    "warnings": {"malformed_mcp_names": 0, "unreadable_transcripts": 0},
    "window": {"start": None, "end": None, "sessions": 1, "sessions_skipped": 0},
}


def _render_html(tmp_path: Path, result: AggregateResult | None = None) -> str:
    """Render dashboard HTML and return it as a string.

    Mirrors ``tests/test_phase3_views.py``'s ``_render_html`` helper.

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


def _extract_render_view_body(html: str) -> str:
    """Slice out the ``_renderView(view)`` function body from rendered HTML.

    Args:
        html: Full rendered dashboard HTML.

    Returns:
        The source text from the ``function _renderView(view)`` marker up
        to (not including) the following ``function setView(view)``
        marker, per ``templates/dashboard.html``'s current shell layout.

    Raises:
        ValueError: If either marker is absent (``str.index`` propagates).
    """
    start = html.index("function _renderView(view)")
    end = html.index("function setView(view)", start)
    return html[start:end]


def _read_mcp_usage_js_source() -> str:
    """Read the raw source text of ``static/views/mcp-usage.js``.

    Not wrapped for a friendlier missing-file message: a plain
    ``FileNotFoundError`` is itself a clear, correct red reason before the
    implementation exists.

    Returns:
        The file's full source text.
    """
    return _MCP_USAGE_JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T9 (F6) -- null-vs-zero handling exists in source (NOT a rendering proof)
# ---------------------------------------------------------------------------


class TestNullVsZeroSourceContainment:
    """T9: source-containment check for F6's null-vs-zero distinction.

    Verified by source containment only; rendering itself is a manual gate
    (Phase 2 exit gate, plan §5 Phase 2 "What CAN and CANNOT be tested").
    """

    def test_source_has_a_null_check(self) -> None:
        """mcp-usage.js source must contain a null-check pattern.

        Looks for ``=== null`` or ``== null``, the two idiomatic JS forms
        for distinguishing "not observable" (null) from "observed as
        zero" (0) on fields like ``sessions_seen_in``.
        """
        content = _read_mcp_usage_js_source()
        assert "=== null" in content or "== null" in content, (
            "mcp-usage.js source has no null-check pattern ('=== null' / "
            "'== null'). F6 requires distinguishing sessions_seen_in: "
            "null from sessions_seen_in: 0."
        )

    def test_source_has_a_null_fallback_literal(self) -> None:
        """mcp-usage.js source must contain a null-state fallback literal.

        Looks for one of the conventional "not observable" copy strings
        the plan names (§2.3 / F6): "unknown", an em dash, or the literal
        phrase "not observable".
        """
        content = _read_mcp_usage_js_source()
        fallback_markers = (
            "unknown",
            "—",  # em dash, "—"
            "not observable",
        )
        assert any(marker in content for marker in fallback_markers), (
            "mcp-usage.js source has no null-state fallback literal "
            "(expected one of 'unknown' / an em dash / 'not observable'). "
            "F6 requires the null case to render visibly differently from "
            "the 0 case."
        )


# ---------------------------------------------------------------------------
# T12 (F9) -- skipped-sessions banner handling exists in source (NOT a
# rendering proof)
# ---------------------------------------------------------------------------


class TestUnreadableTranscriptsBannerSourceContainment:
    """T12: source-containment check for F9's skipped-sessions banner.

    Verified by source containment only; rendering itself is a manual gate
    (Phase 2 exit gate, plan §5 Phase 2 "What CAN and CANNOT be tested").
    """

    def test_source_mentions_unreadable_transcripts(self) -> None:
        """mcp-usage.js source must reference 'unreadable_transcripts'."""
        content = _read_mcp_usage_js_source()
        assert "unreadable_transcripts" in content, (
            "mcp-usage.js source does not mention 'unreadable_transcripts'. "
            "F9's skipped-sessions banner reads "
            "by_mcp_usage.warnings.unreadable_transcripts."
        )

    def test_unreadable_transcripts_is_guarded_by_a_positive_count_check(
        self,
    ) -> None:
        """The 'unreadable_transcripts' reference must be guarded by '> 0'.

        F9 says the banner renders "when
        by_mcp_usage.warnings.unreadable_transcripts > 0" -- searches a
        window around each occurrence of the field name for a '> 0'
        comparison, tolerant of the exact expression shape (e.g.
        ``usage.warnings.unreadable_transcripts > 0`` or
        ``(warnings.unreadable_transcripts || 0) > 0``).
        """
        content = _read_mcp_usage_js_source()
        window = 80
        found_guard = False
        for match in re.finditer("unreadable_transcripts", content):
            start = max(0, match.start() - window)
            end = min(len(content), match.end() + window)
            snippet = content[start:end]
            if re.search(r">\s*0", snippet):
                found_guard = True
                break
        assert found_guard, (
            "mcp-usage.js source mentions 'unreadable_transcripts' but no "
            "'> 0' comparison appears near it. F9's banner must be guarded "
            "by a positive-count check, not rendered unconditionally."
        )


# ---------------------------------------------------------------------------
# Wiring: new top-level "mcp" tab (D-D=(a))
# ---------------------------------------------------------------------------


class TestMcpTabWiring:
    """Verify the new top-level 'mcp' tab is wired into the shell."""

    def test_data_view_mcp_button_present(self, tmp_path: Path) -> None:
        """Rendered HTML must contain a data-view="mcp" tab button.

        D-D=(a): the panel is a new top-level view/tab, sibling to
        basic/detail/advanced -- not embedded inside Breakdown.
        """
        html = _render_html(tmp_path)
        assert 'data-view="mcp"' in html, (
            "Rendered HTML does not contain 'data-view=\"mcp\"'. "
            "The new top-level MCP tab button is not wired in."
        )


class TestMcpTabDispatchReachable:
    """Guard against the plan's documented `_renderView` trap.

    The plan's trap box (§5 Phase 2, step 3) warns that `_renderView`'s
    existing final `else` is a bare catch-all calling `renderEconomics`,
    not an explicit `view === 'advanced'` guard. Two failure modes it
    calls out: shipping the `data-view="mcp"` button with no matching
    branch at all, or inserting the branch in a position where the
    catch-all shadows it first -- both make the new tab silently render
    Economics, with no console error and no visual cue anything is wrong.
    `TestMcpTabWiring` above only proves the button exists; it does not
    prove clicking it reaches `renderMcpUsage`. This test does not
    mandate a specific branch shape (`else if` vs. an explicit dispatch
    table) -- only that an `mcp` comparison exists and is not shadowed by
    a bare catch-all positioned ahead of it.
    """

    def test_renderview_dispatches_mcp_and_is_not_shadowed_by_catchall(
        self, tmp_path: Path
    ) -> None:
        """`_renderView` must compare `view` to 'mcp' before any bare
        catch-all `else { ... }` block that would otherwise shadow it.
        """
        html = _render_html(tmp_path)
        body = _extract_render_view_body(html)

        mcp_match = re.search(r"view\s*===\s*['\"]mcp['\"]", body)
        assert mcp_match, (
            "_renderView's source has no `view === 'mcp'` (or "
            '`view === "mcp"`) comparison. The mcp tab has no reachable '
            "dispatch branch -- clicking it would silently fall through "
            "to the shell's existing catch-all (renderEconomics), per "
            "the plan's trap box."
        )

        # A bare `else { ... }` (i.e. not `else if`) is the documented
        # catch-all. If one appears before the mcp comparison, the mcp
        # branch is unreachable dead code -- the catch-all wins first.
        catchall_pattern = re.compile(r"else(?!\s+if)\s*\{")
        for catchall_match in catchall_pattern.finditer(body):
            if catchall_match.start() < mcp_match.start():
                raise AssertionError(
                    "_renderView contains a bare catch-all `else { ... }` "
                    "positioned before the 'mcp' dispatch comparison. Per "
                    "the plan's trap box, the mcp branch must be inserted "
                    "BEFORE the catch-all (e.g. as an `else if`), not "
                    "after -- otherwise it is unreachable and the mcp "
                    "tab silently renders Economics instead."
                )


# ---------------------------------------------------------------------------
# D-E empty state: tab always renders, even when by_mcp_usage is {}
# ---------------------------------------------------------------------------


class TestEmptyStateSmoke:
    """D-E: the mcp tab renders even when by_mcp_usage is {} (flag off)."""

    def test_render_with_empty_by_mcp_usage_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """render() with a fresh AggregateResult (by_mcp_usage == {}) must
        not raise, and the mcp tab hook must still be present in the
        output -- the D-E empty state, not a missing tab.
        """
        result = AggregateResult()
        assert result.by_mcp_usage == {}
        html = _render_html(tmp_path, result)
        assert 'data-view="mcp"' in html, (
            'The mcp tab must still render its data-view="mcp" hook '
            "when by_mcp_usage is {} (D-E empty state) -- the tab must "
            "not disappear or the shell must not crash before writing it."
        )


# ---------------------------------------------------------------------------
# Populated path: data reaches the client via window.DATA
# ---------------------------------------------------------------------------


class TestPopulatedSmoke:
    """A populated by_mcp_usage payload must reach the client unmodified.

    Status note: this test is GREEN already, before any Phase 2 code
    exists. Phase 1 (merged) already makes render() embed
    AggregateResult.by_mcp_usage into window.DATA unconditionally --
    ``tests/test_dashboard_mcp_usage.py::test_t8_renderer_embeds_by_mcp_usage_content_verbatim``
    already pins that exact server-side contract. This test is kept here
    (not deleted, to avoid true duplication with that stronger equality
    check) as an inherited regression guard scoped to this view's own
    fixture data, not a new Phase 2 assertion -- do not read its "pass"
    as evidence any Phase 2 code was written.
    """

    def test_render_with_populated_by_mcp_usage_embeds_data(
        self, tmp_path: Path
    ) -> None:
        """render() with a populated by_mcp_usage payload must not raise,
        and the payload's server name must appear in the rendered HTML's
        embedded window.DATA JSON -- confirming the data reaches the
        client. This does not assert anything about client-side JS
        execution or DOM output.
        """
        result = AggregateResult(by_mcp_usage=_POPULATED_USAGE)
        html = _render_html(tmp_path, result)
        assert "demo-server" in html, (
            "Rendered HTML does not contain 'demo-server'. The populated "
            "by_mcp_usage payload does not reach window.DATA."
        )
        assert "dormant-server" in html, (
            "Rendered HTML does not contain 'dormant-server'. The "
            "populated by_mcp_usage payload does not reach window.DATA."
        )
