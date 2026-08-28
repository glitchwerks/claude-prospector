"""Tests for the cost-proxy stat wired into the MCP tool-usage view
(issue #262, plan §6c / Phase 3).

These are **source-containment** assertions, not rendering assertions --
this repo has no JS execution capability (no ``package.json``, no
jsdom/playwright in CI). They mirror the established pattern in
``tests/test_mcp_usage_view.py``'s ``TestNullVsZeroSourceContainment`` /
``TestUnreadableTranscriptsBannerSourceContainment`` (T9/T12): they prove
the branching code exists in ``mcp-usage.js``'s source; they do NOT prove
it renders correctly in a browser.

Plan §6c requires, on each server card:
- A fourth stat labelled with an "Est." prefix inside the label itself
  (not only in a footnote), reading ``estimated_result_tokens``.
- That stat's rendering must not assume ``info.estimated_result_tokens``
  always exists -- the field is absent whenever
  ``--track-mcp-call-sizes`` was off, and the existing (non-cost)
  server-card rendering must keep working unchanged in that case. This is
  the crux regression guard.
- Reuse ``formatCountOrUnknown`` so "no result data" renders as
  ``unknown``, not ``0``.
- A one-sentence cost-proxy caveat note, following the existing
  ``.blind-spot`` note pattern (``mcp-usage.js:216-223``).
- ``by_method_tokens`` referenced in (or alongside) ``renderMethodRows``
  so a per-method note appears.
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

    Not wrapped for a friendlier missing-file message: a plain
    ``FileNotFoundError`` is itself a clear, correct red reason if the
    file is ever removed.

    Returns:
        The file's full source text.
    """
    return _MCP_USAGE_JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# "Est. result tokens" stat block exists, with an "Est." prefix in the
# label itself (plan §6c).
# ---------------------------------------------------------------------------


class TestEstimatedResultTokensStatLabelSourceContainment:
    """The server card's fourth stat must reference
    ``estimated_result_tokens`` with an "Est." prefix in its label.
    """

    def test_source_mentions_estimated_result_tokens(self) -> None:
        """mcp-usage.js source must reference 'estimated_result_tokens'."""
        content = _read_mcp_usage_js_source()
        assert "estimated_result_tokens" in content, (
            "mcp-usage.js source does not mention "
            "'estimated_result_tokens'. Plan §6c requires a fourth stat "
            "on each server card reading this field."
        )

    def test_est_prefix_appears_near_the_field_reference(self) -> None:
        """An 'Est.' prefix must appear in a label near a reference to
        estimated_result_tokens -- plan §6c requires the prefix live
        inside the label itself, not only in a footnote elsewhere in the
        file. Uses a window-based search around each occurrence,
        mirroring test_mcp_usage_view.py's T12 guard-search pattern,
        since the exact template-literal structure is the implementer's
        choice.
        """
        content = _read_mcp_usage_js_source()
        window = 200
        found_est_prefix = False
        for match in re.finditer("estimated_result_tokens", content):
            start = max(0, match.start() - window)
            end = min(len(content), match.end() + window)
            snippet = content[start:end]
            if "Est." in snippet or "Est " in snippet:
                found_est_prefix = True
                break
        assert found_est_prefix, (
            "No 'Est.' label prefix found within 200 chars of an "
            "'estimated_result_tokens' reference. Plan §6c requires the "
            "'Est.' prefix inside the stat's label itself, e.g. "
            "'Est. result tokens', not only in a footnote."
        )

    def test_formatcountorunknown_is_reused_for_the_new_stat(self) -> None:
        """The new stat must reuse formatCountOrUnknown (plan §6c) so 'no
        result data' renders as 'unknown', not '0' -- checked via the same
        window-based proximity search as the label check above.
        """
        content = _read_mcp_usage_js_source()
        assert "formatCountOrUnknown" in content, (
            "mcp-usage.js no longer defines/uses formatCountOrUnknown at "
            "all -- the existing F6 null-vs-zero helper must still exist "
            "for the cost stat to reuse."
        )
        window = 200
        found_reuse = False
        for match in re.finditer("estimated_result_tokens", content):
            start = max(0, match.start() - window)
            end = min(len(content), match.end() + window)
            snippet = content[start:end]
            if "formatCountOrUnknown" in snippet:
                found_reuse = True
                break
        assert found_reuse, (
            "No 'formatCountOrUnknown' call found within 200 chars of an "
            "'estimated_result_tokens' reference. Plan §6c requires the "
            "new stat reuse this formatter rather than rendering the raw "
            "number (which would show '0' instead of 'unknown' for "
            "no-result-data servers)."
        )


# ---------------------------------------------------------------------------
# Crux regression guard: the cost stat's rendering path must not assume
# info.estimated_result_tokens always exists, since it is entirely absent
# when --track-mcp-call-sizes was off.
# ---------------------------------------------------------------------------


class TestEstimatedResultTokensAbsenceIsGuarded:
    """The existing (non-cost) server-card rendering must keep working
    unchanged when estimated_result_tokens is absent from a by_server
    entry -- the field access must be guarded, not assumed present.
    """

    def test_field_access_is_guarded_against_absence(self) -> None:
        """At least one presence-guarding pattern (optional chaining,
        a boolean/typeof guard, or an explicit undefined/null comparison)
        must appear around an 'estimated_result_tokens' access. A bare,
        unguarded 'info.estimated_result_tokens.total' with no such
        pattern anywhere in the file would throw for every by_server
        entry collected under plain --track-mcp-calls (no sizes flag),
        which regresses the existing (already-shipped) call-count-only
        rendering path.
        """
        content = _read_mcp_usage_js_source()
        assert "estimated_result_tokens" in content

        guard_patterns = [
            "estimated_result_tokens?.",
            "estimated_result_tokens &&",
            "estimated_result_tokens ?",
            "estimated_result_tokens !=",
            "estimated_result_tokens ==",
            "estimated_result_tokens ||",
            "typeof info.estimated_result_tokens",
            "'estimated_result_tokens' in info",
            '"estimated_result_tokens" in info',
        ]
        assert any(pattern in content for pattern in guard_patterns), (
            "No presence-guard pattern found around "
            "'estimated_result_tokens' (checked for optional chaining "
            "'?.' , '&&'/'?:' short-circuiting, 'typeof', an 'in' check, "
            "or an explicit null/undefined comparison). The rendering "
            "path must not assume info.estimated_result_tokens always "
            "exists -- it is absent whenever --track-mcp-call-sizes was "
            "off, and an unguarded '.total'/'.mean_result_tokens_per_call' "
            "access would throw for every such server-card render."
        )

    def test_no_bare_unguarded_dot_total_access(self) -> None:
        """A direct, unguarded 'info.estimated_result_tokens.total' chain
        (immediate '.total' with no '?.' anywhere in the same access)
        must not appear -- it would throw a TypeError the instant
        estimated_result_tokens is undefined.
        """
        content = _read_mcp_usage_js_source()
        # A bare chain: '.estimated_result_tokens.total' with no '?' in
        # between the two property accesses.
        bare_chain = re.search(r"\.estimated_result_tokens\.total\b", content)
        if bare_chain is None:
            return  # No such access at all -- guard requirement is moot.
        # If a bare chain exists, an optional-chaining variant must exist
        # too (the implementer may have both a guarded read and, e.g., a
        # separate safe local variable derived from it) -- otherwise this
        # is the exact unguarded access the crux guard forbids.
        assert "estimated_result_tokens?." in content, (
            "Found an unguarded 'info.estimated_result_tokens.total' "
            "chain (no '?.' anywhere) with no optional-chaining variant "
            "present elsewhere in the file -- this throws whenever "
            "estimated_result_tokens is absent (the --track-mcp-calls-"
            "only case)."
        )


# ---------------------------------------------------------------------------
# One-sentence cost-proxy caveat note, following the .blind-spot pattern.
# ---------------------------------------------------------------------------


class TestCostProxyCaveatNoteSourceContainment:
    """A one-sentence caveat stating the cost stat is an estimate/proxy
    must exist somewhere in the source, near the cost-rendering code --
    loose containment check, since exact wording is an implementer choice.
    """

    def test_source_mentions_proxy_or_estimate_near_cost_rendering(self) -> None:
        """'proxy' (or 'estimate'/'estimated') must appear within a wide
        window of an 'estimated_result_tokens' reference -- the caveat
        note does not have to be immediately adjacent in the markup, only
        somewhere in the same rendering neighbourhood.
        """
        content = _read_mcp_usage_js_source()
        window = 600
        found_caveat = False
        for match in re.finditer("estimated_result_tokens", content):
            start = max(0, match.start() - window)
            end = min(len(content), match.end() + window)
            snippet = content[start:end].lower()
            if "proxy" in snippet or "estimate" in snippet:
                found_caveat = True
                break
        assert found_caveat, (
            "No 'proxy' or 'estimate'/'estimated' text found within 600 "
            "chars of an 'estimated_result_tokens' reference. F13 "
            "requires the cost stat be explicitly labelled as a proxy -- "
            "the field name alone ('estimated_result_tokens') read out "
            "of context is not sufficient; a caveat sentence (following "
            "the existing .blind-spot note pattern) must accompany it."
        )

    def test_blind_spot_style_note_class_still_present(self) -> None:
        """The existing '.blind-spot' note-block CSS class (the
        established pattern this caveat should reuse or sit alongside)
        must still be present in the source -- a regression guard against
        the caveat note replacing rather than extending that pattern.
        """
        content = _read_mcp_usage_js_source()
        assert "blind-spot" in content, (
            "mcp-usage.js no longer contains the 'blind-spot' note-block "
            "class. Plan §6c directs the cost-proxy caveat to follow this "
            "existing pattern; it must still exist to be followed."
        )


# ---------------------------------------------------------------------------
# by_method_tokens referenced so a per-method note appears (plan §6b/§6c).
# ---------------------------------------------------------------------------


class TestByMethodTokensReferencedInMethodRendering:
    """by_method_tokens must be referenced somewhere in the source, in the
    vicinity of the existing per-method rendering (renderMethodRows or a
    variant) -- loose containment check, exact UI wording is the
    implementer's call.
    """

    def test_source_mentions_by_method_tokens(self) -> None:
        """mcp-usage.js source must reference 'by_method_tokens'."""
        content = _read_mcp_usage_js_source()
        assert "by_method_tokens" in content, (
            "mcp-usage.js source does not mention 'by_method_tokens'. "
            "Plan §6c requires a per-method cost note; compute_tool_usage "
            "already emits this field (Phase 2, aggregator.py) when "
            "track_mcp_call_sizes is True."
        )

    def test_by_method_tokens_reference_sits_near_method_rendering(self) -> None:
        """'by_method_tokens' must appear within a window of either the
        'renderMethodRows' function name or the existing 'by_method'
        (singular map) reference it sits alongside -- proving it is wired
        into the per-method rendering area of the file, not merely
        mentioned in an unrelated comment.
        """
        content = _read_mcp_usage_js_source()
        window = 400
        found_context = False
        for match in re.finditer("by_method_tokens", content):
            start = max(0, match.start() - window)
            end = min(len(content), match.end() + window)
            snippet = content[start:end]
            if "renderMethodRows" in snippet or "by_method" in snippet:
                found_context = True
                break
        assert found_context, (
            "No 'renderMethodRows' or 'by_method' reference found within "
            "400 chars of a 'by_method_tokens' reference. The per-method "
            "cost note must be wired into the existing per-method "
            "rendering area, not left disconnected from it."
        )
