"""Regression tests for issue #279: hide GUID-styled MCP server names from
the MCP breakdown view (``static/views/mcp-usage.js``).

With ``--track-mcp-call-sizes`` enabled, some MCP entries surface as raw
GUIDs (e.g. ``024b99f4-101e-43e2-af7d-dbfcad94f3e8``) instead of a readable
server name -- noise without useful information. Router decision (see issue
#279 discussion): client-side, on-by-default filter inside ``renderServers``,
no new CLI flag or Python/aggregator change.

These are **source-containment** assertions, not rendering assertions --
this repo has no JS execution capability (no ``package.json``, no
jsdom/playwright in CI). They mirror the established pattern in
``tests/test_mcp_usage_view_column_alignment.py`` (issue #284): they prove
the fix's structural markers exist in ``mcp-usage.js``'s source; they do NOT
prove pixel-perfect rendering in a browser. Falsification-checked per the
#284 PR's discipline: verified to fail against the pre-fix source before
being confirmed to pass against the fix.
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


def _extract_function_body(content: str, fn_signature: str) -> str:
    """Extract a top-level function's body text by its declaration.

    Mirrors the extraction approach used in
    ``tests/test_mcp_usage_view_column_alignment.py``: finds the
    declaration, then the next line consisting of just the closing brace
    at the function's indent level (``\\n  }``), and returns everything
    between.

    Args:
        content: Full mcp-usage.js source text.
        fn_signature: The function declaration text to search for, e.g.
            ``"function isGuidLike"``.

    Returns:
        The function's body text (declaration through closing brace,
        exclusive of the trailing brace itself).

    Raises:
        AssertionError: If the declaration isn't found in the source.
    """
    fn_start = content.index(fn_signature)
    fn_end = content.index("\n  }", fn_start)
    return content[fn_start:fn_end]


# ---------------------------------------------------------------------------
# A dedicated, reusable GUID-detection helper must exist (not an inline
# regex at the call site) -- the spec calls for this explicitly so it can
# be referenced from both renderServers and this test.
# ---------------------------------------------------------------------------


class TestIsGuidLikeHelperExists:
    """``isGuidLike`` must exist as a standalone, testable helper."""

    def test_helper_function_is_declared(self) -> None:
        """A `function isGuidLike(...)` declaration must exist."""
        content = _read_mcp_usage_js_source()
        assert "function isGuidLike(" in content, (
            "mcp-usage.js no longer declares a standalone `isGuidLike` "
            "helper -- issue #279 requires a dedicated regex helper "
            "(referenced by both renderServers and this regression test), "
            "not an inline pattern at the call site."
        )

    def test_helper_uses_standard_guid_pattern(self) -> None:
        """The helper's backing regex must match the standard 8-4-4-4-12
        hex-digit UUID/GUID shape, case-insensitively.
        """
        content = _read_mcp_usage_js_source()
        match = re.search(r"const GUID_RE = (/.+?/[a-z]*);", content)
        assert match, (
            "Could not find a `GUID_RE` regex literal in mcp-usage.js -- "
            "has isGuidLike's backing pattern been renamed or inlined?"
        )
        pattern_src = match.group(1)
        # Case-insensitive flag required: hex digits may be upper or
        # lower case per issue #279's spec.
        assert pattern_src.endswith("i"), (
            f"GUID_RE ({pattern_src}) is missing the case-insensitive "
            "'i' flag -- issue #279 requires matching GUIDs regardless "
            "of hex-digit case."
        )
        # Sanity-check the hex group lengths (8-4-4-4-12) appear in the
        # pattern text, without fully re-implementing regex parsing here.
        for group_len in ("8", "4", "4", "4", "12"):
            assert f"{{{group_len}}}" in pattern_src, (
                f"GUID_RE ({pattern_src}) does not appear to declare an "
                f"8-4-4-4-12 hex-digit group (missing a {{{group_len}}} "
                "quantifier) -- the standard GUID/UUID shape."
            )

    def test_helper_matches_a_real_guid_example(self) -> None:
        """The exact GUID example from issue #279's report must satisfy
        the extracted regex pattern (proves the regex is well-formed
        against the reported real-world case, not just structurally
        plausible).
        """
        content = _read_mcp_usage_js_source()
        match = re.search(r"const GUID_RE = /(.+?)/([a-z]*);", content)
        assert match, "Could not find and parse the GUID_RE regex literal."
        pattern, flags_src = match.group(1), match.group(2)
        py_flags = re.IGNORECASE if "i" in flags_src else 0
        compiled = re.compile(pattern, py_flags)

        example = "024b99f4-101e-43e2-af7d-dbfcad94f3e8"
        assert compiled.fullmatch(example), (
            f"GUID_RE ({pattern!r}) does not match the example GUID from "
            f"issue #279's report ({example!r})."
        )
        # Case-insensitivity, concretely.
        assert compiled.fullmatch(example.upper()), (
            f"GUID_RE ({pattern!r}) does not match the uppercase form of "
            f"the example GUID ({example.upper()!r}) -- case-insensitivity "
            "is required."
        )
        # A readable server name must NOT be treated as GUID-like.
        assert not compiled.fullmatch("demo-server"), (
            f"GUID_RE ({pattern!r}) incorrectly matches a normal server "
            "name ('demo-server') -- the pattern is too permissive."
        )


# ---------------------------------------------------------------------------
# renderServers must actually apply the filter (not just have the helper
# sitting unused), and must surface a hidden-count note rather than
# silently dropping entries.
# ---------------------------------------------------------------------------


class TestRenderServersAppliesTheGuidFilter:
    """``renderServers`` must exclude GUID-styled names from the rendered
    list and surface how many were hidden.
    """

    def test_render_servers_calls_is_guid_like(self) -> None:
        """`renderServers` (or a helper it calls) must reference
        `isGuidLike` -- proving the filter is wired in, not just declared.
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServers(")
        assert "isGuidLike" in fn_body, (
            "renderServers no longer references `isGuidLike` -- issue "
            "#279's filter must be applied inside renderServers (around "
            "where `names = Object.keys(byServer).sort()` lives), not "
            "left declared-but-unused."
        )

    def test_render_servers_filters_names_before_rendering_cards(self) -> None:
        """The name list passed to per-card rendering must be filtered
        (e.g. via `.filter(...)`), not the raw, unfiltered key list.
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServers(")
        assert ".filter(" in fn_body, (
            "renderServers does not call `.filter(...)` -- issue #279 "
            "requires excluding GUID-styled names from the rendered "
            "list, which needs a filter step over the sorted key list."
        )

    def test_hidden_count_note_logic_exists(self) -> None:
        """A hidden-count note (naming how many GUID-styled entries were
        excluded) must be produced somewhere in the render path -- issue
        #279 explicitly requires not silently dropping entries with no
        trace.
        """
        content = _read_mcp_usage_js_source()
        assert "hidden" in content.lower(), (
            "mcp-usage.js contains no reference to a 'hidden' count -- "
            "issue #279 requires a visible note stating how many "
            "GUID-styled MCP servers were filtered out, not a silent drop."
        )
        assert "GUID" in content, (
            "mcp-usage.js's hidden-count note text does not mention "
            "'GUID' -- issue #279 requires the note to explain *why* "
            "entries were hidden (GUID-styled names), not just that some "
            "were."
        )

    def test_hidden_count_note_uses_the_blind_spot_style(self) -> None:
        """The hidden-count note must use the file's existing
        `.blind-spot` CSS class -- issue #279 says to follow this file's
        existing CSS-class conventions rather than inventing a new visual
        language.
        """
        content = _read_mcp_usage_js_source()
        # Find the function that builds the hidden-count note by locating
        # a function body that references both 'hidden' semantics and the
        # GUID wording, then assert it emits the blind-spot class.
        note_fn_start = content.index("function renderGuidHiddenNote(")
        note_fn_end = content.index("\n  }", note_fn_start)
        note_fn_body = content[note_fn_start:note_fn_end]
        assert 'class="blind-spot"' in note_fn_body, (
            "The GUID hidden-count note does not use the existing "
            "'.blind-spot' CSS class -- issue #279 requires following "
            "this file's existing CSS-class conventions (matching "
            "renderBlindSpotNote's style) rather than inventing a new "
            "visual language."
        )

    def test_hidden_count_note_omitted_when_nothing_was_hidden(self) -> None:
        """The hidden-count note function must return an empty string
        (render nothing) when the hidden count is zero -- it should only
        appear when GUID-styled entries were actually filtered.
        """
        content = _read_mcp_usage_js_source()
        note_fn_start = content.index("function renderGuidHiddenNote(")
        note_fn_end = content.index("\n  }", note_fn_start)
        note_fn_body = content[note_fn_start:note_fn_end]
        assert re.search(r"===\s*0\s*\)\s*return\s*'';", note_fn_body), (
            "renderGuidHiddenNote does not appear to guard against a "
            "zero hidden-count with an early `return '';` -- the note "
            "should be entirely absent from the rendered output when no "
            "GUID-styled entries were filtered."
        )
