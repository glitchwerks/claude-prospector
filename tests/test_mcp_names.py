"""Tests for claude_prospector.mcp_names — MCP tool-name normalization.

Covers the public ``normalize_mcp_tool_name`` resolver extracted from
``cli/session_summary.py`` (issue #195, spec Decision D5). Behavior must
be a pure move — no change from the original ``_normalize_mcp_tool_name``
contract:

- Well-formed direct-form names (``mcp__<server>__<method>``).
- Well-formed plugin-scoped names
  (``mcp__plugin_<plugin>_<server>__<method>``).
- Server/method segments that themselves contain underscores.
- Malformed names (missing separators, empty server/method segments,
  truncated plugin prefixes) returning ``None``.
- Non-MCP tool names and other non-matching input returning ``None``.
"""

from __future__ import annotations

import pytest

from claude_prospector.cli.session_summary import _normalize_mcp_tool_name
from claude_prospector.mcp_names import normalize_mcp_tool_name


# ---------------------------------------------------------------------------
# Well-formed names
# ---------------------------------------------------------------------------


class TestWellFormedNames:
    """Names that normalize to a '<server>.<method>' string."""

    def test_direct_form_normalizes_server_and_method(self) -> None:
        """Direct form 'mcp__<server>__<method>' normalizes correctly."""
        result = normalize_mcp_tool_name("mcp__azure__storage")
        assert result == "azure.storage"

    def test_plugin_form_strips_plugin_label(self) -> None:
        """Plugin-scoped form strips the plugin label, keeping server.method."""
        result = normalize_mcp_tool_name("mcp__plugin_github_github__create_issue")
        assert result == "github.create_issue"

    def test_plugin_form_with_distinct_plugin_and_server_labels(self) -> None:
        """Plugin label and server label may differ; only server survives."""
        result = normalize_mcp_tool_name("mcp__plugin_myplugin_myserver__method")
        assert result == "myserver.method"

    def test_server_name_containing_underscore_direct_form(self) -> None:
        """An underscore inside the server segment does not break parsing."""
        result = normalize_mcp_tool_name("mcp__my_server__method")
        assert result == "my_server.method"

    def test_method_name_containing_double_underscore_preserved(self) -> None:
        """Only the FIRST '__' is the separator; the rest stays in method."""
        result = normalize_mcp_tool_name("mcp__server__method__with__dunders")
        assert result == "server.method__with__dunders"

    def test_return_value_is_a_string(self) -> None:
        """A well-formed name returns a str, not some other truthy value."""
        result = normalize_mcp_tool_name("mcp__azure__storage")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Malformed / None-returning cases
# ---------------------------------------------------------------------------


class TestMalformedNamesReturnNone:
    """Structurally malformed 'mcp__' names normalize to None."""

    @pytest.mark.parametrize(
        "raw",
        [
            "mcp__",
            "mcp__onlyserver",
            "mcp__server__",
            "mcp____method",
            "mcp__plugin_",
            "mcp__plugin_foo",
            "mcp__plugin_foo_bar",
        ],
        ids=[
            "bare-mcp-prefix",
            "missing-method-separator",
            "empty-method",
            "empty-server",
            "plugin-prefix-no-content",
            "plugin-prefix-single-segment",
            "plugin-form-missing-method-separator",
        ],
    )
    def test_malformed_name_returns_none(self, raw: str) -> None:
        """Each malformed 'mcp__'-prefixed name normalizes to None."""
        assert normalize_mcp_tool_name(raw) is None


# ---------------------------------------------------------------------------
# Non-MCP / non-matching input
# ---------------------------------------------------------------------------


class TestNonMcpInputReturnsNone:
    """Names that never enter MCP parsing at all normalize to None."""

    @pytest.mark.parametrize(
        "raw",
        [
            "Read",
            "Bash",
            "TodoWrite",
            "",
            " mcp__azure__storage",
            "notmcp__azure__storage",
            "mcp",
        ],
        ids=[
            "builtin-tool-name",
            "another-builtin-tool-name",
            "yet-another-builtin-tool-name",
            "empty-string",
            "leading-whitespace-before-prefix",
            "prefix-substring-not-at-start",
            "prefix-without-trailing-underscores",
        ],
    )
    def test_non_mcp_input_returns_none(self, raw: str) -> None:
        """Non-'mcp__'-prefixed input normalizes to None."""
        assert normalize_mcp_tool_name(raw) is None


# ---------------------------------------------------------------------------
# Quirk lock — a documented edge case in the extracted parsing order
# ---------------------------------------------------------------------------


class TestPluginLabelSplitQuirk:
    """Locks a parsing-order quirk so a re-implementation cannot drift.

    Plugin-form parsing splits the plugin label off with a single
    ``str.split("_", 1)`` BEFORE looking for the '__' method separator.
    For "mcp__plugin_x__y", stripping "plugin_" leaves "x__y", and
    ``"x__y".split("_", 1)`` yields ``["x", "_y"]`` — consuming one of
    the two underscores meant to be the '__' separator. The remainder
    "_y" then has no '__' in it, so this normalizes to None rather than
    "x.y". A regex-based or reordered reimplementation could plausibly
    return "x.y" instead; this test pins the original behavior so the
    pure-move extraction cannot silently change it.
    """

    def test_single_char_plugin_and_server_labels_return_none(self) -> None:
        """'mcp__plugin_x__y' returns None under the original split order."""
        assert normalize_mcp_tool_name("mcp__plugin_x__y") is None


# ---------------------------------------------------------------------------
# Compatibility alias — session_summary._normalize_mcp_tool_name
# ---------------------------------------------------------------------------


class TestSessionSummaryAliasStaysImportable:
    """The old private name in session_summary must remain importable.

    Per spec Decision D5, ``session_summary._normalize_mcp_tool_name``
    is re-exported from the new ``mcp_names`` module rather than
    removed, so any external code (or a future refactor) that still
    imports the private name keeps working. These tests assert
    behavioral equivalence (same output for the same input), not
    object identity, so either a direct re-binding or a thin wrapper
    satisfies the contract.
    """

    def test_alias_matches_public_function_for_well_formed_name(self) -> None:
        """The alias normalizes a well-formed name identically."""
        raw = "mcp__azure__storage"
        assert _normalize_mcp_tool_name(raw) == normalize_mcp_tool_name(raw)

    def test_alias_matches_public_function_for_malformed_name(self) -> None:
        """The alias normalizes a malformed name identically (None)."""
        raw = "mcp__server__"
        assert _normalize_mcp_tool_name(raw) == normalize_mcp_tool_name(raw)
        assert _normalize_mcp_tool_name(raw) is None
