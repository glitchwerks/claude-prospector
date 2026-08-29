"""Regression tests for issue #281: hide zero-call ("dormant") MCP server
cards from the MCP breakdown view (``static/views/mcp-usage.js``).

With ``--track-mcp-call-sizes`` enabled, MCP servers/tools with zero calls
in the reporting window still took up a row/cell, adding clutter. This
file already has a deliberate "dormant" feature (F5, issue #248):
``renderServerCard`` renders a dashed-border card with an "available,
unused" badge for servers the transcripts saw but that were never called.
Router decision (issue #281 discussion): hide these zero-``total_calls``
cards by default, but don't destroy the signal -- replace the individual
dormant cards with a single hidden-count note, following the exact same
client-side, on-by-default pattern issue #279's GUID filter established
(no new CLI flag, no Python/aggregator change).

These are **source-containment** assertions, not rendering assertions --
this repo has no JS execution capability (no ``package.json``, no
jsdom/playwright in CI). They mirror the established pattern in
``tests/test_mcp_usage_view_guid_filter.py`` (issue #279): they prove the
fix's structural markers exist in ``mcp-usage.js``'s source; they do NOT
prove pixel-perfect rendering in a browser. Falsification-checked per the
#279/#284 PRs' discipline: verified to fail against the pre-fix source
before being confirmed to pass against the fix. Genuine execution against
synthetic data (mixed active/dormant/GUID servers, the all-hidden empty
state, and the null-vs-zero sessions_seen_in edge case) was additionally
performed via a throwaway Node scratch script during development -- not
retained here since this repo has no JS execution in CI.
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
    ``tests/test_mcp_usage_view_guid_filter.py``: finds the declaration,
    then the next line consisting of just the closing brace at the
    function's indent level (``\\n  }``), and returns everything between.

    Args:
        content: Full mcp-usage.js source text.
        fn_signature: The function declaration text to search for, e.g.
            ``"function isDormantServer"``.

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
# A dedicated, reusable dormant-detection helper must exist (not inline
# logic duplicated at each call site) -- the spec calls for
# renderServerCard's badge condition and renderServers' filter to share
# one definition, matching the isGuidLike precedent from #279.
# ---------------------------------------------------------------------------


class TestIsDormantServerHelperExists:
    """``isDormantServer`` must exist as a standalone, testable helper."""

    def test_helper_function_is_declared(self) -> None:
        """A `function isDormantServer(...)` declaration must exist."""
        content = _read_mcp_usage_js_source()
        assert "function isDormantServer(" in content, (
            "mcp-usage.js does not declare a standalone `isDormantServer` "
            "helper -- issue #281 requires renderServerCard's dormant "
            "badge condition and renderServers' hide-zero-call filter to "
            "share one definition, not duplicated inline logic."
        )

    def test_helper_checks_zero_calls_and_defined_sessions_seen_in(self) -> None:
        """The helper's body must check both `total_calls === 0` and that
        `sessions_seen_in` is neither null nor undefined -- collapsing
        "zero calls, unknown signal" into "dormant" would misrepresent a
        server we have no seen-in-session signal for at all (F6's
        established null-vs-0 distinction).
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function isDormantServer(")
        assert "total_calls === 0" in fn_body, (
            "isDormantServer does not check `total_calls === 0` -- "
            "issue #281's dormant/zero-call predicate must key off "
            "total_calls."
        )
        assert "sessions_seen_in !== null" in fn_body, (
            "isDormantServer does not guard against `sessions_seen_in` "
            "being null -- a server with zero calls AND no seen-in-session "
            "signal must not be silently treated as 'dormant' (F6's "
            "null-vs-0 distinction)."
        )
        assert "sessions_seen_in !== undefined" in fn_body, (
            "isDormantServer does not guard against `sessions_seen_in` "
            "being undefined, matching the null guard above."
        )

    def test_render_server_card_uses_the_shared_helper(self) -> None:
        """`renderServerCard`'s `isDormant` local must be derived from
        `isDormantServer(...)`, not a re-inlined copy of the same
        boolean expression -- proving the two call sites can't drift.
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServerCard(")
        assert "isDormantServer(info)" in fn_body, (
            "renderServerCard no longer calls `isDormantServer(info)` -- "
            "issue #281 requires the card's dormant-badge condition to "
            "use the same shared helper as renderServers' filter."
        )


# ---------------------------------------------------------------------------
# renderServers must actually apply the filter (not just have the helper
# sitting unused), and must surface a hidden-count note rather than
# silently dropping entries.
# ---------------------------------------------------------------------------


class TestRenderServersAppliesTheZeroCallFilter:
    """``renderServers`` must exclude dormant (zero-call) servers from the
    rendered list and surface how many were hidden.
    """

    def test_render_servers_calls_is_dormant_server(self) -> None:
        """`renderServers` must reference `isDormantServer` -- proving the
        filter is wired in, not just declared.
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServers(")
        assert "isDormantServer" in fn_body, (
            "renderServers does not reference `isDormantServer` -- issue "
            "#281's zero-call filter must be applied inside renderServers, "
            "not left declared-but-unused."
        )

    def test_render_servers_filters_dormant_names_before_rendering_cards(
        self,
    ) -> None:
        """The name list passed to per-card rendering must be filtered
        against `isDormantServer` (e.g. via a second `.filter(...)` step
        alongside the existing GUID filter), not just the GUID-filtered
        list.
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServers(")
        filter_calls = re.findall(r"\.filter\(", fn_body)
        assert len(filter_calls) >= 2, (
            "renderServers does not appear to apply two separate "
            "`.filter(...)` steps -- issue #281 requires excluding "
            "dormant (zero-call) names in addition to the existing #279 "
            "GUID filter, as a distinct filtering step so each hidden "
            "count can be reported separately."
        )

    def test_hidden_count_note_logic_exists(self) -> None:
        """A hidden-count note (naming how many dormant/zero-call entries
        were excluded) must be produced somewhere in the render path --
        issue #281 explicitly requires not silently dropping entries with
        no trace, following #279's precedent.
        """
        content = _read_mcp_usage_js_source()
        assert "function renderZeroCallHiddenNote(" in content, (
            "mcp-usage.js does not declare a `renderZeroCallHiddenNote` "
            "function -- issue #281 requires a visible note stating how "
            "many zero-call MCP servers were filtered out, not a silent "
            "drop."
        )
        note_fn_body = _extract_function_body(
            content, "function renderZeroCallHiddenNote("
        )
        assert "never" in note_fn_body.lower() and ("call" in note_fn_body.lower()), (
            "renderZeroCallHiddenNote's text does not appear to explain "
            "*why* entries were hidden (never called / zero calls) -- "
            "issue #281 requires the note to name the reason, not just "
            "the count."
        )

    def test_hidden_count_note_uses_the_blind_spot_style(self) -> None:
        """The hidden-count note must use the file's existing
        `.blind-spot` CSS class -- issue #281 says to follow this file's
        existing CSS-class conventions (matching #279's GUID note) rather
        than inventing a new visual language.
        """
        content = _read_mcp_usage_js_source()
        note_fn_body = _extract_function_body(
            content, "function renderZeroCallHiddenNote("
        )
        assert 'class="blind-spot"' in note_fn_body, (
            "The zero-call hidden-count note does not use the existing "
            "'.blind-spot' CSS class -- issue #281 requires following "
            "this file's existing CSS-class conventions (matching "
            "renderGuidHiddenNote's style) rather than inventing a new "
            "visual language."
        )

    def test_hidden_count_note_omitted_when_nothing_was_hidden(self) -> None:
        """The hidden-count note function must return an empty string
        (render nothing) when the hidden count is zero -- it should only
        appear when dormant entries were actually filtered.
        """
        content = _read_mcp_usage_js_source()
        note_fn_body = _extract_function_body(
            content, "function renderZeroCallHiddenNote("
        )
        assert re.search(r"===\s*0\s*\)\s*return\s*'';", note_fn_body), (
            "renderZeroCallHiddenNote does not appear to guard against a "
            "zero hidden-count with an early `return '';` -- the note "
            "should be entirely absent from the rendered output when no "
            "dormant entries were filtered."
        )

    def test_both_hidden_notes_can_be_combined(self) -> None:
        """renderServers must be able to surface both the GUID-hidden note
        and the zero-call-hidden note in the same render (issue #281
        explicitly allows both notes to coexist) -- proven by both note
        functions being invoked and their results combined, rather than
        one unconditionally replacing the other.
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServers(")
        assert "renderGuidHiddenNote(" in fn_body, (
            "renderServers no longer calls renderGuidHiddenNote -- the "
            "#279 GUID-hidden note must still be produced alongside the "
            "new #281 zero-call-hidden note."
        )
        assert "renderZeroCallHiddenNote(" in fn_body, (
            "renderServers does not call renderZeroCallHiddenNote -- "
            "issue #281's hidden-count note must actually be wired into "
            "renderServers' output."
        )


# ---------------------------------------------------------------------------
# Empty-state wording must not contradict a hidden-count note that just
# explained why nothing is showing.
# ---------------------------------------------------------------------------


class TestEmptyStateDistinguishesRecordedFromAllHidden:
    """When every server is filtered out, the empty-state message must not
    claim "no servers recorded" if servers were in fact recorded (and
    merely hidden) -- that would directly contradict the hidden-count
    note rendered just above it.
    """

    def test_empty_state_branches_on_whether_any_names_existed(self) -> None:
        """renderServers must choose its empty-state message based on
        whether the raw (pre-filter) name list was non-empty, not use one
        unconditional string for both "nothing recorded" and "everything
        hidden".
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServers(")
        assert "names.length === 0" in fn_body, (
            "renderServers no longer checks `names.length === 0` for the "
            "empty-state branch."
        )
        # The empty-state branch must reference the pre-filter name count
        # (allNames) to decide which message to show -- a purely
        # unconditional message can't distinguish the two cases.
        empty_branch_start = fn_body.index("names.length === 0")
        empty_branch = fn_body[empty_branch_start:]
        assert "allNames.length === 0" in empty_branch, (
            "renderServers' empty-state branch does not reference "
            "`allNames.length === 0` -- issue #281 requires "
            "distinguishing 'nothing was ever recorded' from 'servers "
            "exist but every one was filtered out', which needs a check "
            "against the pre-filter name list."
        )

    def test_empty_state_has_two_distinct_messages(self) -> None:
        """Two different empty-state message strings must exist: the
        original "No MCP servers recorded." for the true-empty case, and
        a distinct message for the all-hidden case that doesn't claim
        nothing was recorded.
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServers(")
        assert "No MCP servers recorded." in fn_body, (
            "renderServers no longer contains the original 'No MCP "
            "servers recorded.' message for the true-empty case."
        )
        # The all-hidden case's message must be a distinct string.
        hidden_case_pattern = re.search(
            r"['\"]([^'\"]*hidden[^'\"]*)['\"]", fn_body, re.IGNORECASE
        )
        assert hidden_case_pattern, (
            "Could not find a distinct empty-state message mentioning "
            "'hidden' -- issue #281 requires the all-filtered-out case "
            "to say servers were hidden by filters, not imply nothing "
            "was ever recorded."
        )
        assert hidden_case_pattern.group(1) != "No MCP servers recorded.", (
            "The all-hidden empty-state message is identical to the "
            "true-empty message -- these must be distinct so the wording "
            "doesn't contradict a hidden-count note explaining why "
            "servers exist but aren't shown."
        )
