"""Tests for consolidating the per-card cost-proxy disclaimer into a
single top-level banner (issue #280).

These are **source-containment** assertions, not rendering assertions --
this repo has no JS execution capability (no ``package.json``, no
jsdom/playwright in CI). They mirror the established pattern in
``tests/test_mcp_usage_view_cost_proxy.py`` (``_read_mcp_usage_js_source``,
window-based proximity regex checks) and
``tests/test_mcp_usage_view.py``'s marker-slicing technique
(``_extract_render_view_body``), generalized here to slice *every*
top-level function rather than one hardcoded pair of markers.

Issue #280 asks that the "estimated token" disclaimer currently repeated
on every server card (via a per-card call inside ``renderServerCard``,
see ``tests/test_mcp_usage_view_cost_proxy.py``'s
``TestCostProxyCaveatNoteSourceContainment``) be replaced with a single
banner rendered once at the top of the dashboard -- following the
existing ``renderUnreadableBanner(warnings)`` pattern, which is already
wired once into ``renderMcpUsage``'s top-level template rather than into
each server card.

Naming assumption (a known limitation of source-containment testing
without a JS parser): these tests locate the disclaimer renderer by
name, matching any top-level function whose name contains "Proxy",
"Caveat", or "Disclaimer" -- see ``_disclaimer_named_functions``. This
deliberately excludes "Banner" (``renderUnreadableBanner`` already
matches that and is already wired into ``renderMcpUsage``, which would
make the top-level-wiring assertion below pass vacuously even with no
fix applied) and excludes "Estimat" (``renderEstimatedTokensStat`` --
the *separate*, legitimately per-card numeric stat renderer pinned by
``TestEstimatedResultTokensStatLabelSourceContainment`` in
``test_mcp_usage_view_cost_proxy.py`` -- also matches that root, and
must stay inside ``renderServerCard``). If the implementer renames the
disclaimer renderer away from all three matched roots (e.g. to
``renderTokenEstimateBanner``) or inlines its markup directly into
``renderMcpUsage`` without a separate named function, these tests will
report a false red; that tradeoff is called out to the router rather
than silently accepted.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_USAGE_JS = (
    _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "mcp-usage.js"
)

_FUNCTION_DEF_PREFIX = r"^[ \t]*(?:window\.\w+\s*=\s*)?function\s+"
_TOP_LEVEL_FUNCTION_DEF_RE = re.compile(
    _FUNCTION_DEF_PREFIX + r"(\w+)\s*\(", re.MULTILINE
)
# Deliberately excludes "Banner" and "Estimat" -- see the module
# docstring's "Naming assumption" section for why each would misfire.
_DISCLAIMER_FUNCTION_DEF_RE = re.compile(
    _FUNCTION_DEF_PREFIX + r"(\w*(?:[Pp]roxy|[Cc]aveat|[Dd]isclaimer)\w*)\s*\(",
    re.MULTILINE,
)
# Strips from an unescaped "//" to end-of-line, so a call-site search
# does not mistake a comment mentioning a function name (e.g. "//
# renderCostProxyNote() moved to the top-level banner, see #280") for an
# actual invocation. The negative lookbehind avoids trimming "http://"
# style URLs that might appear in a comment or string.
_LINE_COMMENT_RE = re.compile(r"(?<!:)//.*$", re.MULTILINE)


def _read_mcp_usage_js_source() -> str:
    """Read the raw source text of ``static/views/mcp-usage.js``.

    Not wrapped for a friendlier missing-file message: a plain
    ``FileNotFoundError`` is itself a clear, correct red reason if the
    file is ever removed.

    Returns:
        The file's full source text.
    """
    return _MCP_USAGE_JS.read_text(encoding="utf-8")


def _strip_line_comments(text: str) -> str:
    """Remove ``//``-style line comments from JS source text.

    Args:
        text: JS source span to strip.

    Returns:
        ``text`` with comment tails removed.
    """
    return _LINE_COMMENT_RE.sub("", text)


def _split_top_level_functions(content: str) -> dict[str, str]:
    """Slice JS source into named top-level function spans.

    Generalizes ``test_mcp_usage_view.py``'s
    ``_extract_render_view_body`` marker-slicing technique (which uses
    one hardcoded pair of markers) to every top-level function
    declaration in the file: each function's span runs from its own
    declaration up to (not including) the next top-level function
    declaration, or end-of-file for the last one. Matches both a plain
    ``function name(...)`` declaration (e.g. ``renderServerCard``) and a
    named function expression assigned to ``window`` (e.g.
    ``window.renderMcpUsage = function renderMcpUsage(root) {``), since
    this file uses the latter form for its exported view entry point.

    Args:
        content: Full JS source text.

    Returns:
        Mapping of function name to its source span. If a name is
        declared more than once (unexpected for this file's
        conventions), the last declaration wins.
    """
    matches = list(_TOP_LEVEL_FUNCTION_DEF_RE.finditer(content))
    spans: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        spans[name] = content[start:end]
    return spans


def _disclaimer_named_functions(content: str) -> list[str]:
    """Return top-level function names that reference the disclaimer
    concept ("Proxy", "Caveat", or "Disclaimer" in the name).

    Name-based rather than wording-based, so it tolerates the
    implementer renaming the existing ``renderCostProxyNote`` function
    during the issue #280 refactor (e.g. to ``renderCostProxyBanner`` --
    note "Banner" alone would not match; the roots checked are "Proxy",
    "Caveat", "Disclaimer") without needing to guess the exact caveat
    sentence, which is an implementer wording choice. See the module
    docstring's "Naming assumption" section for the roots deliberately
    excluded and why.

    Args:
        content: Full JS source text.

    Returns:
        Sorted list of distinct matching function names.
    """
    return sorted(set(_DISCLAIMER_FUNCTION_DEF_RE.findall(content)))


# ---------------------------------------------------------------------------
# Issue #280: the cost-proxy disclaimer must be consolidated into a single
# top-level banner, not repeated once per server card.
# ---------------------------------------------------------------------------


class TestCostProxyDisclaimerConsolidatedAtTopLevel:
    """The cost-proxy caveat must render once, at the top level of the
    dashboard, not once per server card.
    """

    def test_a_disclaimer_named_render_function_exists(self) -> None:
        """Sanity precondition: some top-level function whose name
        contains "Proxy"/"Caveat"/"Disclaimer" must still exist in the
        source (e.g. the existing ``renderCostProxyNote``, or a renamed
        replacement such as ``renderCostProxyBanner``). If none exists,
        the remaining tests in this class cannot locate the disclaimer
        renderer at all and would otherwise pass vacuously. This test is
        expected to be green already (it pins a precondition, not the
        issue #280 fix itself).
        """
        content = _read_mcp_usage_js_source()
        disclaimer_names = _disclaimer_named_functions(content)
        assert disclaimer_names, (
            "No top-level function with 'Proxy'/'Caveat'/'Disclaimer' in "
            "its name (e.g. 'renderCostProxyNote') found in "
            "mcp-usage.js. Issue #280's fix is expected to keep (or "
            "rename) the existing cost-proxy disclaimer renderer, not "
            "delete the concept entirely."
        )

    def test_disclaimer_render_function_not_called_from_within_render_server_card(
        self,
    ) -> None:
        """No disclaimer-named function may be called from inside
        ``renderServerCard``'s function body.

        This is both the "moved to top-level" check and the
        "no duplication" regression guard: ``renderServerCard`` is
        invoked once per server card, so any call site living inside its
        body renders per-card, which is exactly the duplication issue
        #280 asks to remove. If this call site is ever reintroduced here
        in the future, this test must fail again. Comment-only mentions
        of the function name are stripped before the search, so a stray
        code comment referencing the old call site cannot mask a
        genuine fix (nor cause a false failure).
        """
        content = _read_mcp_usage_js_source()
        functions = _split_top_level_functions(content)
        has_render_server_card = "renderServerCard" in functions
        assert has_render_server_card, (
            "mcp-usage.js no longer defines a top-level 'renderServerCard' "
            "function -- cannot verify the disclaimer has moved out of "
            "the per-server-card renderer."
        )
        disclaimer_names = _disclaimer_named_functions(content)
        server_card_body = _strip_line_comments(functions["renderServerCard"])
        offending = [
            name for name in disclaimer_names if f"{name}(" in server_card_body
        ]
        assert not offending, (
            f"renderServerCard's function body still calls "
            f"{offending!r}. Issue #280 requires the cost-proxy "
            "disclaimer to be removed from the per-server-card renderer "
            "and shown once at the top level instead, following the "
            "existing renderUnreadableBanner(warnings) pattern."
        )

    def test_disclaimer_render_function_called_from_within_top_level_render_mcp_usage(
        self,
    ) -> None:
        """A disclaimer-named function must be called from within
        ``renderMcpUsage``'s top-level assembly body -- the same
        function that wires in ``renderUnreadableBanner`` /
        ``renderBlindSpotNote`` / ``renderServers`` -- so the disclaimer
        renders once, as a top-level banner, rather than nowhere at all.
        """
        content = _read_mcp_usage_js_source()
        functions = _split_top_level_functions(content)
        has_render_mcp_usage = "renderMcpUsage" in functions
        assert has_render_mcp_usage, (
            "mcp-usage.js no longer defines a top-level 'renderMcpUsage' "
            "function -- cannot verify a top-level banner is wired in."
        )
        disclaimer_names = _disclaimer_named_functions(content)
        top_level_body = _strip_line_comments(functions["renderMcpUsage"])
        called_at_top_level = any(
            f"{name}(" in top_level_body for name in disclaimer_names
        )
        assert called_at_top_level, (
            "None of the disclaimer-named functions "
            f"({disclaimer_names!r}) are called from within "
            "renderMcpUsage's top-level assembly body. Issue #280 "
            "requires a single top-level banner -- following the "
            "existing renderUnreadableBanner(warnings) pattern -- that "
            "states the cost-proxy caveat once, wired into renderMcpUsage "
            "alongside renderUnreadableBanner / renderBlindSpotNote / "
            "renderServers."
        )

    def test_top_level_banner_call_site_is_guarded_by_data_presence(self) -> None:
        """The top-level banner call site (or the disclaimer function it
        calls) should render conditionally on data presence -- mirroring
        the existing conditional pattern already used for
        ``renderUnreadableBanner``/``renderZeroCallHiddenNote`` -- rather
        than unconditionally on every visit to the mcp tab, since the
        disclaimer is meaningless when no server has
        ``estimated_result_tokens`` data at all
        (``--track-mcp-call-sizes`` was off).

        Loose containment check: requires both a reference to
        ``estimated_result_tokens`` (the data the guard must key off)
        and a conditional-structure marker (a guarded 'if', an
        '.some(...)' existence check, or boolean short-circuiting) within
        a combined window covering the top-level call site and the
        disclaimer function's own body -- since the guard may live in
        either place, at the implementer's choice. A bare ternary/'&&'
        with no reference to ``estimated_result_tokens`` nearby does not
        count -- template-literal renderers use '?'/'&&' pervasively for
        unrelated reasons, so that alone would pass regardless of
        whether the banner is actually guarded.
        """
        content = _read_mcp_usage_js_source()
        functions = _split_top_level_functions(content)
        has_render_mcp_usage = "renderMcpUsage" in functions
        assert has_render_mcp_usage, (
            "mcp-usage.js no longer defines a top-level 'renderMcpUsage' "
            "function -- cannot verify a top-level banner is wired in."
        )
        disclaimer_names = _disclaimer_named_functions(content)
        top_level_body = _strip_line_comments(functions["renderMcpUsage"])

        call_match = None
        called_name = None
        for name in disclaimer_names:
            call_match = re.search(re.escape(f"{name}("), top_level_body)
            if call_match:
                called_name = name
                break
        assert call_match, (
            "No top-level call site to a disclaimer-named function found "
            "in renderMcpUsage -- see "
            "test_disclaimer_render_function_called_from_within_top_"
            "level_render_mcp_usage for the primary wiring check."
        )

        window = 200
        start = max(0, call_match.start() - window)
        end = min(len(top_level_body), call_match.end() + window)
        call_site_snippet = top_level_body[start:end]
        disclaimer_own_body = _strip_line_comments(functions.get(called_name, ""))
        combined = call_site_snippet + disclaimer_own_body

        conditional_markers = ("if (", "if(", ".some(", "&&", "?")
        has_conditional = any(marker in combined for marker in conditional_markers)
        # Case-insensitive "estimated" (not the literal field name) so a
        # helper like "hasEstimatedTokens(usage)" guarding the call site
        # counts too, not just a direct "estimated_result_tokens" access.
        has_data_reference = "estimated" in combined.lower()
        assert has_conditional and has_data_reference, (
            "No data-presence guard found for the top-level cost-proxy "
            "banner: expected both an 'estimated'-related reference and "
            "a conditional-structure marker ('if (', '.some(', '&&', "
            "'?') within 200 chars of the top-level call site or inside "
            "the disclaimer function's own body. The banner should "
            "render conditionally (only when at least one server has "
            "estimated_result_tokens data), mirroring the existing "
            "renderUnreadableBanner / renderZeroCallHiddenNote "
            "conditional pattern, not unconditionally on every visit to "
            "the mcp tab."
        )
