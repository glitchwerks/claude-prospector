"""Tests for issue #283: collapse/group a server's per-method tool rows
into a single summary row once the server exposes more distinct methods
than a threshold, with an expand affordance that reveals the full
per-method breakdown on demand (``static/views/mcp-usage.js``).

Context: servers like GitHub expose 20+ individual ``mcp__github__*``
tools, each currently rendered as its own row via
``renderMethodRows(info.by_method, info.by_method_tokens)`` inside
``.methods``. This dominates the dashboard view. Router decision (issue
#283 discussion): a threshold-based collapse -- when a server's distinct
method/tool count exceeds a threshold, render one summary row ("N tools,
TOTAL calls") instead of one row per method, with a toggle/expand
affordance (``<details>``/``<summary>``, or a button/clickable element
wired to a click handler) that reveals the existing
``renderMethodRows``-produced breakdown on demand. Servers at or under the
threshold keep rendering every method row directly -- no behavior change
for the existing, already-tested happy path.

These are **source-containment** assertions, not rendering assertions --
this repo has no JS execution capability (no ``package.json``, no
jsdom/playwright in CI). They mirror the established pattern in
``tests/test_mcp_usage_view_guid_filter.py`` (issue #279) and
``tests/test_mcp_usage_view_zero_call_filter.py`` (issue #281): they prove
the feature's structural markers exist in ``mcp-usage.js``'s source; they
do NOT prove pixel-perfect rendering or that a click actually toggles
visibility in a browser (that composition -- toggle wired to reveal the
breakdown -- is not robustly text-verifiable and is left to implementer/
reviewer scrutiny, per this file's own docstring caveat below).

Design choices deliberately left open to the implementer (this file does
NOT pin a specific shape for these):

- The exact threshold number (e.g. "more than 5 distinct methods"). Tests
  below assert that *some* numeric threshold/comparison exists against a
  per-server method count, not a specific magic number.
- Whether the expand affordance is a native ``<details>``/``<summary>``
  element or a button/clickable element with an ``addEventListener``/
  ``onclick`` handler.
- Whether the collapsed summary row lives inside ``.methods`` or in a
  sibling wrapper. ``tests/test_mcp_usage_view_column_alignment.py``
  (issue #284) pins ``.methods`` as a shared 3-column CSS grid where
  every ``.row`` must emit exactly 3 children (grid auto-placement
  wraps every 3 items). A collapsed summary row is a structurally
  different kind of row (not a per-method entry), so these tests do
  NOT assert it is a ``.methods`` child, nor do they assert anything
  about DOM placement or child count -- that would risk forcing a
  contradiction with #284's frozen contract. This is a deliberate
  scope exemption, not an oversight.

Regression-guard note: no existing test file asserts, as a named/
standalone check, that ``renderMethodRows`` renders one row per
``by_method`` entry for servers under any particular count -- the closest
precedent is ``tests/test_mcp_usage_view.py``'s populated-path smoke test
and ``tests/test_mcp_usage_view_cost_proxy.py``'s proximity checks around
``renderMethodRows``/``by_method``. Since no such standalone test exists
to defer to, ``TestFullBreakdownRemainsReachable`` below (declaration +
call-site-count checks on ``renderMethodRows``) is this file's
light-touch stand-in guard, and must remain green before and after the
#283 implementation.
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


# ---------------------------------------------------------------------------
# 1. A threshold/collapse-condition mechanism must exist: some numeric
#    comparison gating collapsed vs. expanded rendering, keyed off a
#    per-server method/tool count. This is the crux of the "20+ tools
#    dominate the view" problem statement -- without it, every server
#    (regardless of size) renders every method row today.
# ---------------------------------------------------------------------------


class TestToolCountThresholdMechanismExists:
    """A numeric threshold/comparison against the per-server method count
    must exist somewhere in the source -- the gating condition for
    collapsed vs. expanded rendering (issue #283's design decision).

    Does not pin the exact threshold number, nor whether it is a bare
    literal or a named constant (e.g. ``const TOOL_COLLAPSE_THRESHOLD =
    5;`` compared later via an identifier) -- only that a length/count
    check against a per-server method/tool collection is compared
    against *some* numeric threshold, one way or another.
    """

    def test_a_method_or_tool_count_is_compared_against_a_threshold(
        self,
    ) -> None:
        """Either of the following must appear in the source:

        - A ``.length`` expression on a method/tool-ish collection (its
          own identifier containing "method"/"tool", or a bare
          ``Object.keys(...).length``) compared against a number or an
          identifier via ``>``/``>=``/``<``/``<=`` (covers both a
          literal threshold and a named-constant threshold used
          in-line), OR
        - A named threshold constant declaration (e.g. ``const
          TOOL_COLLAPSE_THRESHOLD = 5;``) whose name is *also*
          referenced in a ``.length`` comparison somewhere in the
          source -- proving the gate is both declared and wired into an
          actual comparison, not just declared and left unused. (Per
          CodeRabbit review on PR #293: a declared-but-unreferenced
          constant does not prove a gate exists.)
        """
        content = _read_mcp_usage_js_source()

        length_threshold_pattern = re.compile(
            r"(?:Object\.keys\([^)]*\)|[\w$.]*(?:[Mm]ethod|[Tt]ool)\w*)"
            r"\.length\s*(?:>=|>|<=|<)\s*[\w$.]+"
        )
        reverse_length_threshold_pattern = re.compile(
            r"[\w$.]+\s*(?:>=|>|<=|<)\s*"
            r"(?:Object\.keys\([^)]*\)|[\w$.]*(?:[Mm]ethod|[Tt]ool)\w*)\.length"
        )

        named_constant_match = re.search(
            r"const\s+(?P<name>\w*(?:THRESHOLD|COLLAPSE|MAX)\w*)\s*=\s*\d+",
            content,
            re.IGNORECASE,
        )
        named_constant_is_used_in_a_length_comparison = False
        if named_constant_match is not None:
            constant_name = re.escape(named_constant_match.group("name"))
            named_constant_is_used_in_a_length_comparison = bool(
                re.search(
                    rf"\.length\s*(?:>=|>|<=|<)\s*{constant_name}\b",
                    content,
                )
                or re.search(
                    rf"\b{constant_name}\s*(?:>=|>|<=|<)\s*[\w$.]*\.length",
                    content,
                )
            )

        found = bool(
            length_threshold_pattern.search(content)
            or reverse_length_threshold_pattern.search(content)
            or named_constant_is_used_in_a_length_comparison
        )
        assert found, (
            "mcp-usage.js has no numeric threshold comparison against a "
            "method/tool-count collection, and no named threshold "
            "constant (e.g. 'const TOOL_COLLAPSE_THRESHOLD = 8;') that "
            "is actually referenced in a '.length' comparison. Issue "
            "#283 requires a threshold gate deciding whether a server's "
            "methods render as individual rows or collapse into a "
            "single summary row -- declaring a threshold constant "
            "without using it in a comparison does not satisfy this."
        )


# ---------------------------------------------------------------------------
# 2. A collapsed/summary-row rendering path must exist for the
#    over-threshold case: something producing ONE row/element that
#    reports an aggregate (tool count + total calls), not per-method
#    detail.
# ---------------------------------------------------------------------------


class TestCollapsedSummaryRowRenderingPathExists:
    """A collapsed-summary-row rendering path must exist: some mechanism
    that computes an aggregate over a server's per-method data (rather
    than iterating it row-by-row), which is the behavioral signature of
    a "N tools, TOTAL calls" summary row.

    Does not require this to live in a function separate from
    ``renderMethodRows`` -- the collapse branch may reasonably live
    inside that same function, since it already receives ``by_method``.
    That is an implementation-shape choice left open here.
    """

    def test_an_aggregate_is_computed_over_the_per_method_data(self) -> None:
        """Either of the following must appear in the source:

        - A ``.reduce(`` call over ``Object.values(...)`` (or over a
          method/tool-named collection) -- the idiomatic way to sum
          per-method call counts into one aggregate, OR
        - A template-literal count-summary label: an interpolated
          expression referencing ``length``/``count``/``size``, followed
          shortly by "tool(s)"/"method(s)" (e.g.
          `` `${methodNames.length} tools` ``) -- the idiomatic way to
          phrase a collapsed tool-count label. (A bare CSS class like
          ``class="methods"`` sitting near an unrelated interpolation
          does not count -- the interpolated expression itself must
          look like a count.)
        """
        content = _read_mcp_usage_js_source()

        reduce_over_values_pattern = re.compile(r"Object\.values\([^)]*\)\s*\.reduce\(")
        reduce_near_method_collection_pattern = re.compile(
            r"[\w$.]*(?:[Mm]ethod|[Tt]ool)\w*\s*\.reduce\("
        )
        pluralized_count_label_pattern = re.compile(
            r"\$\{[^}]{0,60}(?:length|count|Count|size)[^}]{0,60}\}"
            r"[^`]{0,20}\b(?:tools?|methods?)\b",
            re.IGNORECASE,
        )

        found = bool(
            reduce_over_values_pattern.search(content)
            or reduce_near_method_collection_pattern.search(content)
            or pluralized_count_label_pattern.search(content)
        )
        assert found, (
            "mcp-usage.js has no aggregate-computation pattern (a "
            "'.reduce(' over per-method values, or a pluralized "
            "'N tools'/'N methods' count-label template) anywhere in "
            "the source. Issue #283 requires a collapsed summary row "
            "that reports a tool COUNT alongside an aggregate call "
            "total (e.g. 'N tools, TOTAL calls') for over-threshold "
            "servers -- this mechanism does not exist yet."
        )


# ---------------------------------------------------------------------------
# 3. An expand/reveal affordance must exist: <details>/<summary>, OR a
#    clickable element wired to a toggle handler.
# ---------------------------------------------------------------------------


class TestExpandAffordanceExists:
    """An expand/reveal affordance must exist -- a native
    ``<details>``/``<summary>`` element, OR a button/clickable element
    with an associated click handler (``addEventListener('click', ...)``
    or ``onclick=``) -- so the collapsed summary row can be expanded to
    reveal the full per-method breakdown.
    """

    def test_a_details_summary_or_click_toggle_affordance_exists(self) -> None:
        """The source must contain at least one of: a ``<details``
        element, a ``<summary`` element, an ``addEventListener('click'``
        wiring, or an ``onclick=`` attribute.
        """
        content = _read_mcp_usage_js_source()
        affordance_patterns = (
            r"<details",
            r"<summary(?!\s+class=\"[^\"]*stat)",
            r"addEventListener\(\s*['\"]click['\"]",
            r"onclick\s*=",
        )
        found = any(re.search(pattern, content) for pattern in affordance_patterns)
        assert found, (
            "mcp-usage.js contains no <details>/<summary> element and no "
            "click-toggle wiring (addEventListener('click', ...) or "
            "onclick=). Issue #283 requires an expand/reveal affordance "
            "so a collapsed server's full per-method breakdown can be "
            "revealed on demand."
        )


# ---------------------------------------------------------------------------
# 4. Progressive disclosure, not data loss: the full renderMethodRows
#    breakdown must still be reachable/rendered somewhere in the file
#    when collapsing is in play -- collapsing must not delete the
#    per-method rendering machinery.
#
#    Note: whether the expand affordance is *actually wired* to reveal
#    renderMethodRows's specific output (vs. merely coexisting with it
#    elsewhere in the file) is not something a text-containment check can
#    robustly prove -- a proximity match between the toggle identifier
#    and renderMethodRows would be brittle against reasonable formatting
#    choices. That composition is left to implementer/reviewer scrutiny,
#    not asserted here.
# ---------------------------------------------------------------------------


class TestFullBreakdownRemainsReachable:
    """The existing per-method breakdown machinery must still exist and
    still be invoked -- collapsing must be progressive disclosure, not a
    replacement that deletes the detailed view.
    """

    def test_render_method_rows_is_still_declared(self) -> None:
        """``function renderMethodRows(`` must still be declared."""
        content = _read_mcp_usage_js_source()
        assert "function renderMethodRows(" in content, (
            "mcp-usage.js no longer declares `renderMethodRows` -- issue "
            "#283's collapse feature must compose with the existing "
            "per-method rendering machinery, not delete it."
        )

    def test_render_method_rows_is_still_called_somewhere(self) -> None:
        """``renderMethodRows(`` must still be called from at least one
        call site (i.e. referenced more than just in its own
        declaration) -- proving the detailed breakdown is still wired
        into the render path somewhere, reachable for the expanded case.
        """
        content = _read_mcp_usage_js_source()
        occurrences = len(re.findall(r"renderMethodRows\(", content))
        assert occurrences >= 2, (
            f"'renderMethodRows(' appears {occurrences} time(s) in "
            "mcp-usage.js -- expected at least 2 (its own declaration "
            "plus at least one call site). Issue #283's collapsed view "
            "must still reach the full per-method breakdown somewhere, "
            "not just declare renderMethodRows unused."
        )


# ---------------------------------------------------------------------------
# 5 & 6. Regression guard: servers at or under the threshold must be
#    unaffected -- every method row still renders directly, matching
#    today's behavior. No standalone existing test pins this by name
#    (see module docstring); this guard defers to (and must not
#    contradict) the populated-path smoke tests in
#    tests/test_mcp_usage_view.py and tests/test_mcp_usage_view_cost_proxy.py.
#    Router checklist item 6 (renderMethodRows itself, or its call site,
#    must still exist/be referenced) is covered by
#    TestFullBreakdownRemainsReachable above -- both its declaration
#    check and its >=2-occurrence (declaration + call site) check
#    already establish this; a third identical substring check would be
#    pure duplication, so none is added here.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 7. CodeRabbit review of PR #293 (issue #283): issue #283's body asks to
#    "roll up all tools belonging to one MCP server into a single row
#    (aggregate calls/tokens)". The collapsed summary row
#    (``renderMethodsBlock``) aggregates a CALL count today ("N tools,
#    TOTAL calls"), but not a TOKEN count -- even though
#    ``info.by_method_tokens`` (the per-method token-estimate map) is
#    already populated and already used elsewhere in this same file
#    (``renderMethodTokensNote``, ``renderEstimatedTokensStat``). The
#    token half of "aggregate calls/tokens" is missing.
#
#    ``by_method_tokens`` is only populated when ``--track-mcp-call-
#    sizes`` was passed -- it is entirely absent otherwise -- so the
#    aggregate must be guarded, mirroring how ``renderEstimatedTokensStat``
#    / ``renderCostProxyNote`` already guard on ``estimated_result_tokens``
#    presence (``tests/test_mcp_usage_view_cost_proxy.py``). These tests
#    do NOT require a token aggregate to be computed/rendered when
#    ``by_method_tokens`` is absent -- only that when it IS present, the
#    collapsed summary computes and displays an aggregate over it.
# ---------------------------------------------------------------------------


def _extract_function_source(content: str, function_name: str) -> str:
    """Extract one top-level function's source text by name.

    Slices from ``function <function_name>(`` up to (but not including)
    the next top-level ``function `` declaration, so proximity checks
    scoped to this one function don't accidentally match unrelated
    per-method rendering code elsewhere in the file (e.g.
    ``renderMethodTokensNote``, which already references
    ``by_method_tokens`` for a different purpose).

    Args:
        content: The full source text to search.
        function_name: The bare function name (no ``function`` keyword,
            no parens).

    Returns:
        The matched slice, or an empty string if the function is not
        declared at all.
    """
    declaration = re.search(rf"function {re.escape(function_name)}\(", content)
    if declaration is None:
        return ""
    start = declaration.start()
    next_top_level_fn = re.search(r"\nfunction \w", content[start + 1 :])
    if next_top_level_fn is None:
        return content[start:]
    return content[start : start + 1 + next_top_level_fn.start()]


class TestCollapsedSummaryAggregatesTokensAlongsideCalls:
    """The collapsed ``<details><summary>`` row (``renderMethodsBlock``)
    must aggregate a TOKEN total alongside the existing CALL total, per
    issue #283's "aggregate calls/tokens" requirement (CodeRabbit finding
    on PR #293, since only the call aggregate was implemented).

    All checks are scoped to ``renderMethodsBlock``'s own source window
    (not the whole file) -- ``by_method_tokens`` already appears
    elsewhere in the file for an unrelated per-method note
    (``renderMethodTokensNote``), so an unscoped, whole-file containment
    check would pass today without the collapsed summary actually
    aggregating anything.
    """

    def test_render_methods_block_is_still_declared(self) -> None:
        """Sanity precondition for every other test in this class: if
        ``renderMethodsBlock`` is renamed or removed, every proximity
        check below is scoped to an empty string and would fail for a
        confusing reason. Fail loudly and specifically here instead.
        """
        content = _read_mcp_usage_js_source()
        assert "function renderMethodsBlock(" in content, (
            "mcp-usage.js no longer declares `renderMethodsBlock` -- the "
            "collapsed-summary rendering path from issue #283 must "
            "still exist for this class's token-aggregation checks to "
            "mean anything."
        )

    def test_summary_computes_a_token_aggregate_from_by_method_tokens(
        self,
    ) -> None:
        """Within ``renderMethodsBlock``'s own source, an aggregate must
        be computed over a token-named collection -- a ``.reduce(`` call
        (or equivalent summation) whose subject is ``by_method_tokens``
        or an equivalently token-named parameter/variable within ~120
        characters before the call. A bare mention of
        ``by_method_tokens`` (e.g. merely passing it through to the
        existing ``renderMethodRows`` call for the expanded breakdown)
        does not satisfy this -- the collapsed summary must itself
        derive a total.
        """
        content = _read_mcp_usage_js_source()
        block = _extract_function_source(content, "renderMethodsBlock")
        assert block, "renderMethodsBlock not found -- see the sanity test above."

        token_reduce_found = False
        for match in re.finditer(r"\.reduce\(", block):
            preceding = block[max(0, match.start() - 120) : match.start()]
            if re.search(r"[Tt]okens?", preceding):
                token_reduce_found = True
                break

        assert token_reduce_found, (
            "renderMethodsBlock has no aggregate ('.reduce(') computed "
            "over a token-named collection (by_method_tokens, or an "
            "equivalently-named parameter/variable). Issue #283 asks "
            "the collapsed summary row to 'aggregate calls/tokens' -- "
            "only the call aggregate exists today; the token aggregate "
            "is missing."
        )

    def test_token_aggregate_presence_is_guarded(self) -> None:
        """``by_method_tokens`` is only populated when
        ``--track-mcp-call-sizes`` was passed -- it is entirely absent
        otherwise. Mirroring the guard pattern already established for
        ``estimated_result_tokens``
        (``tests/test_mcp_usage_view_cost_proxy.py``), a presence-guard
        must appear within ``renderMethodsBlock``: optional chaining, a
        truthy/short-circuit guard, a fallback default (``|| {}``), or
        reuse of ``formatCountOrUnknown``.
        """
        content = _read_mcp_usage_js_source()
        block = _extract_function_source(content, "renderMethodsBlock")
        assert block, "renderMethodsBlock not found -- see the sanity test above."

        guard_patterns = (
            r"by_method_tokens\s*\?\.",
            r"by_method_tokens\s*&&",
            r"by_method_tokens\s*\|\|",
            r"by_method_tokens\s*\?[^.]",
            r"[\w$.]*[Tt]okens?\w*\s*\|\|\s*\{\}",
            r"typeof\s+[\w$.]*[Tt]okens?\w*",
            r"formatCountOrUnknown\([^)]*[Tt]okens?",
        )
        found_guard = any(re.search(pattern, block) for pattern in guard_patterns)
        assert found_guard, (
            "renderMethodsBlock has no presence-guard around token data "
            "(checked for optional chaining, '&&'/'||' short-circuiting, "
            "a '|| {}' fallback default, or formatCountOrUnknown reuse). "
            "by_method_tokens is entirely absent when "
            "--track-mcp-call-sizes was off, so an unguarded aggregate "
            "would throw or silently misbehave for that case."
        )

    def test_token_aggregate_is_rendered_in_the_summary_text(self) -> None:
        """The computed token aggregate must actually be displayed --
        some interpolated expression must sit inside a template literal
        alongside a 'token(s)' label, not merely be computed and
        discarded.
        """
        content = _read_mcp_usage_js_source()
        block = _extract_function_source(content, "renderMethodsBlock")
        assert block, "renderMethodsBlock not found -- see the sanity test above."

        token_label_pattern = re.compile(
            r"\$\{[^}]{0,80}\}[^`]{0,40}\b[Tt]okens?\b", re.IGNORECASE
        )
        assert token_label_pattern.search(block), (
            "renderMethodsBlock has no interpolated value rendered "
            "alongside a 'token(s)' label in a template literal -- the "
            "collapsed summary row must display the aggregate token "
            "figure it computes, not just compute it."
        )
