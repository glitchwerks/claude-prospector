"""Tests for issue #282: client-side name filter for the MCP usage view
(``static/views/mcp-usage.js``).

With ``--track-mcp-call-sizes`` enabled, the MCP breakdown view can list
many servers/tools with no way to narrow the view to ones the user cares
about. Router decision (see issue #282's briefing): a client-side search
box, not a CLI flag -- ``window.DATA.by_mcp_usage`` already carries the
full server/tool data client-side, so filtering is a pure rendering-layer
concern confined to this one file, with no aggregator/CLI changes.

Most of these are **source-containment** assertions. A focused Node.js
regression also executes the real renderer with a minimal DOM boundary;
it is skipped when Node.js is unavailable. The source checks mirror the
established pattern in
``tests/test_mcp_usage_view_guid_filter.py`` (issue #279) and
``tests/test_mcp_usage_view_zero_call_filter.py`` (issue #281): they prove
the feature's structural markers exist in ``mcp-usage.js``'s source --
element markup, event wiring, and a filter-predicate function.

Contract pinned by this test file (names chosen here as the frozen
contract for the implementer to satisfy):

- A text input with ``id="mcp-name-filter"`` exists in the rendered
  markup, with a placeholder/aria-label hinting at its filter-by-name
  purpose.
- An ``input`` event listener is wired to that element.
- A standalone ``function matchesNameFilter(name, query)`` predicate
  exists, performing a case-insensitive substring match (mirroring the
  dedicated-helper convention ``isGuidLike``/``isDormantServer``
  established by issues #279/#281).
- That predicate is actually invoked (not just declared) in both a
  server-name context and a tool/method-name context, per the issue's
  explicit "servers/tools" scope.
- The pre-existing GUID-hiding (#279) and zero-call-hiding (#281) filters
  remain declared and wired -- the new filter must compose with them, not
  replace them.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_USAGE_JS = (
    _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "mcp-usage.js"
)
_CP_UTILS_JS = _REPO_ROOT / "src" / "claude_prospector" / "static" / "cp-utils.js"

_FILTER_INPUT_ID = "mcp-name-filter"
_FILTER_PREDICATE_NAME = "matchesNameFilter"


def _read_mcp_usage_js_source() -> str:
    """Read the raw source text of ``static/views/mcp-usage.js``.

    Not wrapped for a friendlier missing-file message: a plain
    ``FileNotFoundError`` is itself a clear, correct red reason before the
    implementation exists (matches ``tests/test_mcp_usage_view.py``'s
    convention).

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
            ``"function matchesNameFilter"``.

    Returns:
        The function's body text (declaration through closing brace,
        exclusive of the trailing brace itself).

    Raises:
        ValueError: If the declaration isn't found in the source -- a
            clear, correct red reason before the feature is implemented.
    """
    fn_start = content.index(fn_signature)
    fn_end = content.index("\n  }", fn_start)
    return content[fn_start:fn_end]


def _extract_input_tag(content: str, input_id: str) -> str:
    """Extract the full ``<input ...>`` tag whose ``id`` matches ``input_id``.

    Args:
        content: Full mcp-usage.js source text.
        input_id: The exact ``id`` attribute value to locate (e.g.
            ``"mcp-name-filter"``).

    Returns:
        The full tag text, from ``<input`` through the closing ``>``.

    Raises:
        ValueError: If the id marker or an enclosing ``<input`` tag isn't
            found -- a clear, correct red reason before the input exists.
    """
    marker = f'id="{input_id}"'
    idx = content.index(marker)
    tag_start = content.rindex("<input", 0, idx)
    tag_end = content.index(">", idx)
    return content[tag_start : tag_end + 1]


def _invocation_windows(content: str, fn_name: str, size: int = 400) -> list[str]:
    """Return context windows around each *invocation* of ``fn_name``.

    Skips the function's own ``function <fn_name>(`` declaration site so
    callers only see call sites, proving the function is actually used
    somewhere rather than declared-but-dead.

    Args:
        content: Full mcp-usage.js source text.
        fn_name: The bare function name to search for (e.g.
            ``"matchesNameFilter"``).
        size: Number of characters of context to include on each side of
            a call site.

    Returns:
        A list of context-window strings, one per non-declaration call
        site found.
    """
    windows: list[str] = []
    for match in re.finditer(re.escape(fn_name) + r"\(", content):
        prefix = content[max(0, match.start() - 9) : match.start()]
        if prefix.endswith("function "):
            continue
        start = max(0, match.start() - size)
        end = min(len(content), match.end() + size)
        windows.append(content[start:end])
    return windows


# ---------------------------------------------------------------------------
# A discoverable text input (the search/filter box) must exist in the
# rendered markup.
# ---------------------------------------------------------------------------


class TestNameFilterInputExists:
    """A text input for filtering by name must exist in the view's markup."""

    def test_input_element_with_distinguishing_id_exists(self) -> None:
        """An ``<input id="mcp-name-filter">`` must appear in the source."""
        content = _read_mcp_usage_js_source()
        assert f'id="{_FILTER_INPUT_ID}"' in content, (
            f"mcp-usage.js does not contain an element with "
            f'id="{_FILTER_INPUT_ID}" -- issue #282 requires a '
            "discoverable name-filter input in the rendered markup."
        )

    def test_input_is_a_text_style_input(self) -> None:
        """The filter input's ``type`` must be ``text`` or ``search``."""
        content = _read_mcp_usage_js_source()
        tag = _extract_input_tag(content, _FILTER_INPUT_ID)
        assert ('type="text"' in tag) or ('type="search"' in tag), (
            f"The #{_FILTER_INPUT_ID} input tag ({tag!r}) does not declare "
            'type="text" or type="search" -- issue #282 calls for a free-'
            "text name/substring filter box."
        )

    def test_input_has_a_purpose_hinting_placeholder_or_aria_label(self) -> None:
        """The input must hint at its filter-by-name purpose to users."""
        content = _read_mcp_usage_js_source()
        tag = _extract_input_tag(content, _FILTER_INPUT_ID)
        placeholder_match = re.search(r'placeholder="([^"]*)"', tag)
        aria_match = re.search(r'aria-label="([^"]*)"', tag)
        assert placeholder_match or aria_match, (
            f"The #{_FILTER_INPUT_ID} input tag ({tag!r}) has neither a "
            "placeholder nor an aria-label -- issue #282's filter box must "
            "hint at its purpose to users."
        )
        hint_text = (
            (placeholder_match.group(1) if placeholder_match else "")
            + " "
            + (aria_match.group(1) if aria_match else "")
        ).lower()
        assert ("filter" in hint_text) or ("search" in hint_text), (
            f"The #{_FILTER_INPUT_ID} input's placeholder/aria-label "
            f"({hint_text!r}) does not mention 'filter' or 'search' -- it "
            "must hint that this box narrows the view."
        )
        assert "name" in hint_text, (
            f"The #{_FILTER_INPUT_ID} input's placeholder/aria-label "
            f"({hint_text!r}) does not mention 'name' -- it must hint that "
            "this box filters by server/tool *name*, not some other field."
        )


# ---------------------------------------------------------------------------
# A dedicated, reusable name-matching predicate must exist (not an inline
# comparison duplicated at each call site) -- mirrors the isGuidLike /
# isDormantServer precedent from issues #279 / #281.
# ---------------------------------------------------------------------------


class TestNameFilterPredicateExists:
    """``matchesNameFilter`` must exist as a standalone, testable helper."""

    def test_predicate_function_declared_with_two_params(self) -> None:
        """A ``function matchesNameFilter(name, query)``-shaped declaration
        must exist (a two-parameter function, whatever the parameter
        names).
        """
        content = _CP_UTILS_JS.read_text(encoding="utf-8")
        assert re.search(
            rf"function {_FILTER_PREDICATE_NAME}\(\s*\w+\s*,\s*\w+\s*\)", content
        ), (
            f"cp-utils.js does not satisfy the shared-helper contract: "
            f"it does not declare a standalone "
            f"`function {_FILTER_PREDICATE_NAME}(name, query)` helper -- "
            "issue #282 requires a dedicated, testable name-matching "
            "predicate, not inline comparisons duplicated at each filter "
            "call site."
        )

    def test_predicate_is_case_insensitive_substring_match(self) -> None:
        """The predicate must lower-case at least one operand and use a
        substring check -- issue #282 requires a case-insensitive
        substring/pattern match, not an exact or case-sensitive
        comparison. Only one ``.toLowerCase()`` is required inside the
        predicate itself: the other operand may already be normalized by
        the caller (e.g. once, at the point the query is read off the
        input), so this does not pin normalization to happen twice inside
        the predicate body.
        """
        content = _CP_UTILS_JS.read_text(encoding="utf-8")
        fn_body = _extract_function_body(content, f"function {_FILTER_PREDICATE_NAME}(")
        lower_count = fn_body.count(".toLowerCase()")
        assert lower_count >= 1, (
            f"{_FILTER_PREDICATE_NAME}'s body calls `.toLowerCase()` "
            f"{lower_count} time(s) -- issue #282 requires a case-"
            "insensitive comparison, which needs at least one operand "
            "normalized inside the predicate."
        )
        assert ".includes(" in fn_body, (
            f"{_FILTER_PREDICATE_NAME}'s body does not call `.includes(` "
            "-- issue #282 requires a substring match against the query."
        )


# ---------------------------------------------------------------------------
# The input must be wired to a live 'input' event, reading its own value.
# ---------------------------------------------------------------------------


class TestNameFilterWiredToInputEvent:
    """An ``input`` event listener must be registered on the filter box."""

    def test_input_event_listener_registered(self) -> None:
        """An ``addEventListener('input', ...)`` call must exist somewhere
        in the source.
        """
        content = _read_mcp_usage_js_source()
        assert re.search(r"addEventListener\(\s*['\"]input['\"]", content), (
            "mcp-usage.js does not register any `addEventListener('input', "
            "...)` listener -- issue #282's filter box must re-apply the "
            "filter live as the user types."
        )

    def test_input_event_listener_is_wired_to_the_filter_input(self) -> None:
        """At least one ``input``-event listener registration must be near
        a reference to the filter input's id -- proving it's wired to
        *this* element, not some unrelated input.
        """
        content = _read_mcp_usage_js_source()
        for match in re.finditer(r"addEventListener\(\s*['\"]input['\"]", content):
            window = content[max(0, match.start() - 400) : match.end() + 400]
            if _FILTER_INPUT_ID in window:
                return
        raise AssertionError(
            f"No `addEventListener('input', ...)` registration was found "
            f"near a reference to #{_FILTER_INPUT_ID} -- the listener does "
            "not appear to be wired to the name-filter input."
        )

    def test_listener_reads_the_inputs_value(self) -> None:
        """The wiring around the filter input's ``input`` listener must
        read ``.value`` -- the query string has to come from the input
        itself.
        """
        content = _read_mcp_usage_js_source()
        for match in re.finditer(r"addEventListener\(\s*['\"]input['\"]", content):
            window = content[max(0, match.start() - 400) : match.end() + 400]
            if _FILTER_INPUT_ID in window and ".value" in window:
                return
        raise AssertionError(
            f"No `.value` read was found near an 'input'-event listener "
            f"wired to #{_FILTER_INPUT_ID} -- the query string driving the "
            "filter must come from the input element's own value."
        )


# ---------------------------------------------------------------------------
# The predicate must actually be used -- and used for BOTH server names
# and per-method/tool names, per the issue's explicit "servers/tools"
# scope. This requires at least two independent call sites: one predicate
# call sitting near server-rendering context is not sufficient proof that
# tool/method names are filtered too (a single server-only call site could
# otherwise satisfy an overly permissive method-context check via nearby
# CSS/markup strings that say nothing about actual per-method filtering).
# ---------------------------------------------------------------------------


class TestNameFilterInvokedAtIndependentCallSites:
    """``matchesNameFilter`` must have at least two distinct call sites --
    the minimum needed to filter both a server name and each per-method/
    tool name independently, rather than one call site doing double duty.
    """

    def test_predicate_has_at_least_two_call_sites(self) -> None:
        """At least two non-declaration invocations of
        ``matchesNameFilter`` must exist in the source.
        """
        content = _read_mcp_usage_js_source()
        windows = _invocation_windows(content, f"CP.{_FILTER_PREDICATE_NAME}")
        assert len(windows) >= 2, (
            f"{_FILTER_PREDICATE_NAME} has only {len(windows)} call "
            "site(s) -- issue #282 requires filtering both server names "
            "and per-method/tool names, which needs at least two "
            "independent invocation sites (one applied to the server "
            "name, one applied to each method/tool name), not a single "
            "call site reused for both."
        )

    def test_all_predicate_calls_use_the_shared_cp_helper(self) -> None:
        """A stale bare call must not bypass the shared ``CP`` helper."""
        content = _read_mcp_usage_js_source()
        unqualified = re.findall(
            rf"(?<![.\w]){_FILTER_PREDICATE_NAME}\(",
            content,
        )
        assert not unqualified, (
            "mcp-usage.js contains an unqualified matchesNameFilter() call; "
            "all renderer paths must use the shared CP.matchesNameFilter() "
            "helper from cp-utils.js."
        )


def test_matching_server_and_tool_queries_render_without_errors(
    tmp_path: Path,
) -> None:
    """Server matches keep all methods; tool matches narrow method rows."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; JavaScript execution test skipped")

    runner = tmp_path / "mcp-name-filter-check.js"
    runner.write_text(
        """
const fs = require('fs');
const vm = require('vm');
global.window = {
  DATA: {
    by_mcp_usage: {
      by_server: {
        github: {
          total_calls: 5,
          sessions_seen_in: 1,
          avg_calls_per_active_session: 5,
          by_method: { create_issue: 3, list_repos: 2 },
        },
      },
      by_tool: { create_issue: 3, list_repos: 2 },
      warnings: {},
      window: { start: null, end: null },
    },
  },
};
global.document = {
  getElementById: () => null,
  createElement: () => ({ id: '', textContent: '' }),
  head: { appendChild: () => {} },
};
vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'));
global.CP = window.CP;
vm.runInThisContext(fs.readFileSync(process.argv[3], 'utf8'));

let onInput = null;
const filterInput = {
  value: '',
  addEventListener: (event, handler) => {
    if (event === 'input') onInput = handler;
  },
};
const serverList = { innerHTML: '' };
const root = {
  innerHTML: '',
  classList: { add: () => {} },
  querySelector: (selector) => (
    selector === '#mcp-name-filter' ? filterInput : serverList
  ),
};
window.renderMcpUsage(root);

function search(query) {
  filterInput.value = query;
  onInput();
  return serverList.innerHTML;
}

process.stdout.write(JSON.stringify({
  server: search('github'),
  tool: search('issue'),
}));
""",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [node, str(runner), str(_CP_UTILS_JS), str(_MCP_USAGE_JS)],
        capture_output=True,
        check=True,
        text=True,
    )
    rendered = json.loads(completed.stdout)

    assert "github" in rendered["server"]
    assert "create_issue" in rendered["server"]
    assert "list_repos" in rendered["server"]
    assert "github" in rendered["tool"]
    assert "create_issue" in rendered["tool"]
    assert "list_repos" not in rendered["tool"]


class TestNameFilterAppliesToServerNames:
    """``matchesNameFilter`` must be invoked in a server-name context."""

    def test_predicate_invoked_in_a_server_name_context(self) -> None:
        """At least one invocation of ``matchesNameFilter`` must sit near a
        server-rendering marker (``renderServers``, ``renderServerCard``,
        ``byServer``, or ``server-card``).
        """
        content = _read_mcp_usage_js_source()
        windows = _invocation_windows(content, f"CP.{_FILTER_PREDICATE_NAME}")
        assert windows, (
            f"{_FILTER_PREDICATE_NAME} is declared but never invoked -- "
            "issue #282 requires the predicate to actually be applied "
            "somewhere in the render path, not left declared-but-unused."
        )
        server_markers = (
            "renderServers(",
            "renderServerCard(",
            "byServer",
            "server-card",
        )
        assert any(
            any(marker in window for marker in server_markers) for window in windows
        ), (
            f"No invocation of {_FILTER_PREDICATE_NAME} sits near a "
            "server-rendering marker (renderServers / renderServerCard / "
            "byServer / server-card) -- issue #282 requires the filter to "
            "apply to MCP *server* names."
        )


class TestNameFilterAppliesToToolMethodNames:
    """``matchesNameFilter`` must be invoked in a tool/method-name context.

    Markers here are deliberately restricted to the *data* the tool/
    method names actually live in (``by_method``) or the function that
    renders them (``renderMethodRows``) -- not CSS/markup strings like
    ``.row`` or ``method-name``, which can appear near a server-only call
    site (e.g. inside ``renderServers``' own template literal) without
    proving any per-method filtering actually happens.
    """

    def test_predicate_invoked_in_a_method_tool_name_context(self) -> None:
        """At least one invocation of ``matchesNameFilter`` must sit near
        ``renderMethodRows`` or ``by_method`` -- the function and data
        field that carry per-method/tool names.
        """
        content = _read_mcp_usage_js_source()
        windows = _invocation_windows(content, f"CP.{_FILTER_PREDICATE_NAME}")
        assert windows, (
            f"{_FILTER_PREDICATE_NAME} is declared but never invoked -- "
            "issue #282 requires the predicate to actually be applied "
            "somewhere in the render path, not left declared-but-unused."
        )
        method_markers = ("renderMethodRows(", "by_method")
        assert any(
            any(marker in window for marker in method_markers) for window in windows
        ), (
            f"No invocation of {_FILTER_PREDICATE_NAME} sits near "
            "renderMethodRows or by_method -- issue #282 explicitly "
            "requires the filter to apply to MCP *tool*/method names too, "
            "not servers alone."
        )


# ---------------------------------------------------------------------------
# The pre-existing GUID-hiding (#279) and zero-call-hiding (#281) filters
# must remain declared and wired -- the new filter must compose with,
# not replace, them.
# ---------------------------------------------------------------------------


class TestExistingFiltersRemainIntact:
    """Issues #279's and #281's filters must survive the #282 addition."""

    def test_guid_filter_helper_still_present(self) -> None:
        """``isGuidLike`` and ``renderGuidHiddenNote`` (issue #279) must
        still be declared.
        """
        content = _read_mcp_usage_js_source()
        assert "function isGuidLike(" in content, (
            "isGuidLike (issue #279's GUID filter helper) is no longer "
            "declared -- the new #282 name filter must compose with, not "
            "replace, the existing GUID filter."
        )
        assert "function renderGuidHiddenNote(" in content, (
            "renderGuidHiddenNote (issue #279's hidden-count note) is no "
            "longer declared -- the #282 name filter must not remove it."
        )

    def test_zero_call_filter_helper_still_present(self) -> None:
        """``isDormantServer`` and ``renderZeroCallHiddenNote`` (issue
        #281) must still be declared.
        """
        content = _read_mcp_usage_js_source()
        assert "function isDormantServer(" in content, (
            "isDormantServer (issue #281's zero-call filter helper) is no "
            "longer declared -- the new #282 name filter must compose "
            "with, not replace, the existing zero-call filter."
        )
        assert "function renderZeroCallHiddenNote(" in content, (
            "renderZeroCallHiddenNote (issue #281's hidden-count note) is "
            "no longer declared -- the #282 name filter must not remove it."
        )

    def test_render_servers_still_wires_existing_filters(self) -> None:
        """``renderServers`` must still reference both ``isGuidLike`` and
        ``isDormantServer`` -- proving the existing filters remain wired
        into the render path, not just declared.
        """
        content = _read_mcp_usage_js_source()
        fn_body = _extract_function_body(content, "function renderServers(")
        assert "isGuidLike" in fn_body, (
            "renderServers no longer references isGuidLike -- issue #282's "
            "name filter must not disconnect the existing #279 GUID "
            "filter from the render path."
        )
        assert "isDormantServer" in fn_body, (
            "renderServers no longer references isDormantServer -- issue "
            "#282's name filter must not disconnect the existing #281 "
            "zero-call filter from the render path."
        )
