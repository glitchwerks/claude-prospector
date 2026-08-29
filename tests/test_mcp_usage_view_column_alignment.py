"""Regression tests for issue #284: MCP dashboard method-row column
misalignment (the "Usage count" / "est. tokens" columns did not line up
across rows).

These are **source-containment** assertions, not rendering assertions --
this repo has no JS execution capability (no ``package.json``, no
jsdom/playwright in CI). They mirror the established pattern in
``tests/test_mcp_usage_view.py`` (T9/T12) and
``tests/test_mcp_usage_view_cost_proxy.py``: they prove the fix's
structural markers exist in ``mcp-usage.js``'s source; they do NOT prove
pixel-perfect rendering in a browser. That was instead verified manually
for this fix via a headless-Chrome screenshot comparison (see the PR
description) -- not repeatable in CI, so it is not encoded here.

Root cause (confirmed via headless-Chrome screenshot diff, not just source
reading): ``.methods .row`` was a flex container with
``justify-content: space-between``. That produces a stable 2-column
layout (name flush-left, count flush-right) for exactly 2 children, but
issue #262 added a 3rd child (the per-method tokens note) to some/most
method rows. With 3 flex children, only the first and last are
flush-anchored -- the middle item (the count) floats to a position based
on the surrounding items' rendered widths, so it lands in a different x
position on every row (and, for a method name wide enough to fill the
card, can overflow the card entirely and end up glued directly after the
name text instead of in a column).

Fix: ``.methods`` became a single shared CSS grid
(``grid-template-columns: minmax(0, 1fr) auto auto``) and ``.row``
switched to ``display: contents`` so its children become direct grid
items of ``.methods`` -- sharing one set of column tracks across every
row, which is what makes the count/tokens columns line up. That
restructure requires every row to emit exactly 3 children (grid
auto-placement wraps to a new row after every 3 items in DOM order;
a row emitting only 2 children would shift every subsequent row's cells
by one column) -- so ``renderMethodTokensNote`` was changed to always
return a (possibly empty) third ``<div class="n">`` cell instead of ``''``
when no per-method token stats exist.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_USAGE_JS = (
    _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "mcp-usage.js"
)


def _read_mcp_usage_js_source() -> str:
    """Read the raw source text of ``static/views/mcp-usage.js``.

    Returns:
        The file's full source text.
    """
    return _MCP_USAGE_JS.read_text(encoding="utf-8")


def _extract_css_rule_block(content: str, selector: str) -> str:
    """Extract one CSS rule's ``{ ... }`` body from the embedded ``css``
    template literal, by selector text.

    Args:
        content: Full mcp-usage.js source text.
        selector: The exact selector text preceding the rule's ``{``
            (e.g. ``".lmu-style .server-card .methods .row"``).

    Returns:
        The rule body, not including the braces.

    Raises:
        AssertionError: If the selector isn't found in the source.
    """
    marker = selector + " {"
    idx = content.find(marker)
    assert idx != -1, (
        f"Could not find CSS rule {selector!r} in mcp-usage.js -- has the "
        "selector been renamed or removed?"
    )
    body_start = idx + len(marker)
    body_end = content.index("}", body_start)
    return content[body_start:body_end]


# ---------------------------------------------------------------------------
# .methods is a shared CSS grid (not each .row being its own flex box) --
# this is what makes column positions consistent across every method row.
# ---------------------------------------------------------------------------


class TestMethodsIsASharedGridSourceContainment:
    """``.methods`` must be a single grid container with fixed column
    tracks shared by every ``.row`` -- the structural fix for #284's
    per-row column drift.
    """

    def test_methods_rule_uses_display_grid(self) -> None:
        """The `.methods` CSS rule must declare `display: grid`."""
        content = _read_mcp_usage_js_source()
        block = _extract_css_rule_block(content, ".lmu-style .server-card .methods")
        assert "display: grid" in block, (
            "'.lmu-style .server-card .methods' no longer declares "
            "'display: grid'. Issue #284's fix relies on .methods being a "
            "single shared grid so every .row's cells land in the same "
            "column tracks -- reverting this reopens the per-row column "
            "drift."
        )

    def test_methods_rule_declares_three_column_tracks(self) -> None:
        """The `.methods` CSS rule must declare a grid-template-columns
        with exactly 3 tracks (name, count, tokens-note).
        """
        content = _read_mcp_usage_js_source()
        block = _extract_css_rule_block(content, ".lmu-style .server-card .methods")
        match = re.search(r"grid-template-columns:\s*([^;]+);", block)
        assert match, (
            "'.lmu-style .server-card .methods' has no "
            "grid-template-columns declaration -- #284's fix requires "
            "fixed column tracks shared across every method row."
        )
        # A bare split on whitespace at the top level is good enough here:
        # the shipped value ("minmax(0, 1fr) auto auto") has 3
        # space-separated top-level track components once the internal
        # minmax(...) comma is normalised out. Collapse "minmax(0" "1fr)"
        # back into a rough count of tracks by counting close-parens /
        # bare tokens -- loose but sufficient to catch an accidental
        # 2-column regression (the exact bug this guards against: 2
        # tracks would silently misalign the 3rd cell again).
        tracks_text = match.group(1).replace(",", " ")
        track_count = tracks_text.count(")") + len(
            [t for t in tracks_text.split() if "(" not in t and ")" not in t]
        )
        assert track_count >= 3, (
            f"grid-template-columns {match.group(1)!r} does not appear to "
            "declare 3 column tracks (name, count, tokens-note). #284's "
            "fix requires exactly 3 fixed tracks."
        )

    def test_row_rule_uses_display_contents(self) -> None:
        """The `.methods .row` CSS rule must declare `display: contents`
        so its children become direct grid items of the shared
        `.methods` grid -- the mechanism that makes columns actually
        line up (vs. each row sizing its own independent grid/flex box).
        """
        content = _read_mcp_usage_js_source()
        block = _extract_css_rule_block(
            content, ".lmu-style .server-card .methods .row"
        )
        assert "display: contents" in block, (
            "'.lmu-style .server-card .methods .row' no longer declares "
            "'display: contents'. Without it, each .row lays out its own "
            "independent box (flex or grid) and column positions drift "
            "row-to-row based on that row's own content widths -- "
            "reopening #284."
        )

    def test_row_rule_no_longer_uses_space_between_flex(self) -> None:
        """Regression guard: the pre-#284 buggy pattern (`.methods .row`
        as a flex container with `justify-content: space-between`) must
        not reappear -- that is the exact root cause #284 fixed.
        """
        content = _read_mcp_usage_js_source()
        block = _extract_css_rule_block(
            content, ".lmu-style .server-card .methods .row"
        )
        assert "justify-content" not in block, (
            "'.lmu-style .server-card .methods .row' declares "
            "'justify-content' again -- this is the exact pre-#284 "
            "flex + space-between pattern whose 3rd child (added by "
            "issue #262's per-method tokens note) loses its flush-right "
            "anchor and floats to a row-dependent position, causing the "
            "count/tokens columns to misalign."
        )


# ---------------------------------------------------------------------------
# renderMethodTokensNote must always emit a 3rd grid cell (never '') so
# grid auto-placement doesn't wrap early and shift every later row by one
# column.
# ---------------------------------------------------------------------------


class TestRenderMethodTokensNoteAlwaysEmitsAThirdCell:
    """``renderMethodTokensNote`` must return a placeholder ``<div class=
    "n">`` cell (not ``''``) when a method has no per-method token stats --
    a bare ``''`` would drop that row to 2 children, and because ``.row``
    is ``display: contents`` inside a shared grid, a 2-child row shifts
    every subsequent row's cells by one column (issue #284).
    """

    def test_no_stats_branch_does_not_return_bare_empty_string(self) -> None:
        """The `if (!stats) return ...` branch inside
        renderMethodTokensNote must not be a bare `return '';` -- that was
        the pre-fix behavior that dropped a row to 2 children.
        """
        content = _read_mcp_usage_js_source()
        fn_start = content.index("function renderMethodTokensNote")
        fn_end = content.index("\n  }", fn_start)
        fn_body = content[fn_start:fn_end]

        assert "return '';" not in fn_body, (
            "renderMethodTokensNote still has a bare `return '';` branch. "
            "Because `.methods .row` is `display: contents` inside a "
            "shared 3-column grid, a row with only 2 children shifts "
            "every subsequent row's cells by one column -- #284's fix "
            "requires this branch to return a placeholder cell instead."
        )

    def test_no_stats_branch_returns_a_placeholder_n_cell(self) -> None:
        """The `if (!stats) return ...` branch must return a `<div
        class="n">` placeholder, matching the shape of the populated
        branch's cell (same class, so it participates in the same grid
        column and picks up the same `.n` styling).
        """
        content = _read_mcp_usage_js_source()
        fn_start = content.index("function renderMethodTokensNote")
        fn_end = content.index("\n  }", fn_start)
        fn_body = content[fn_start:fn_end]

        match = re.search(r"if\s*\(!stats\)\s*return\s*(.+?);", fn_body)
        assert match, (
            "Could not find an `if (!stats) return ...;` guard in "
            "renderMethodTokensNote -- has the no-data branch been "
            "restructured? #284 requires this branch to still exist and "
            "emit a placeholder cell."
        )
        returned = match.group(1)
        assert '<div class="n">' in returned, (
            f"renderMethodTokensNote's no-stats branch returns {returned!r}, "
            "which is not a '<div class=\"n\">' placeholder cell. #284's "
            "fix requires every row to emit exactly 3 children so grid "
            "auto-placement (via .row's display: contents) doesn't wrap "
            "early and shift later rows' columns."
        )


# ---------------------------------------------------------------------------
# Ground truth for scope: the reported bug names "Usage count" and
# "est. tokens" -- these map to .methods .row's cells, not the separate
# .stats grid (issue #284's diagnostic hypothesis 2, ruled out).
# ---------------------------------------------------------------------------


class TestReportedColumnsMapToMethodRowsNotStatsGrid:
    """Scope guard: proves (via source, mirroring the rendered-HTML check
    done manually for this fix) that "Usage count" / "est. tokens" -- the
    columns named in issue #284's report -- are produced by
    ``renderMethodRows``/``renderMethodTokensNote`` (the per-method row),
    not by ``renderServerCard``'s separate ``.stats`` grid (whose labels
    are "Total calls" / "Est. result tokens", a different, unaddressed
    5-in-2-column layout question -- see issue #284's diagnostic
    hypothesis 2, intentionally out of scope for this fix).
    """

    def test_stats_grid_labels_do_not_use_the_reported_column_names(self) -> None:
        """The `.stats` grid's stat labels must not literally be "Usage
        count" -- confirming the reported bug is not about `.stats`.
        """
        content = _read_mcp_usage_js_source()
        assert "Usage count" not in content, (
            "mcp-usage.js now contains a literal 'Usage count' label -- "
            "if this was added to the .stats grid, issue #284's scope "
            "assumption (that 'Usage count' refers to the per-method row's "
            "count cell, not a .stats label) needs re-verifying."
        )

    def test_est_tokens_text_lives_in_render_method_tokens_note(self) -> None:
        """The literal "est." token-count text (the reported "est.
        tokens" column) must be produced by renderMethodTokensNote, not
        renderEstimatedTokensStat (the .stats grid's cost stat).
        """
        content = _read_mcp_usage_js_source()
        fn_start = content.index("function renderMethodTokensNote")
        fn_end = content.index("\n  }", fn_start)
        fn_body = content[fn_start:fn_end]
        assert "(est." in fn_body, (
            "renderMethodTokensNote no longer contains the '(est. ... "
            "tok)' text -- issue #284's reported 'est. tokens' column is "
            "this per-method note, not the .stats grid's 'Est. result "
            "tokens' stat."
        )
