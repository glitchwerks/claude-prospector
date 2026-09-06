"""Regression tests for the agent-stats lookup view from issue #295."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render


_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENTS_JS = _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "agents.js"
_CP_UTILS_JS = _REPO_ROOT / "src" / "claude_prospector" / "static" / "cp-utils.js"
_ECONOMICS_JS = (
    _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "economics.js"
)
_MCP_USAGE_JS = (
    _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / "mcp-usage.js"
)


def _read_agents_js_source() -> str:
    """Read the agent lookup view source.

    Returns:
        The complete JavaScript source for the agent lookup view.
    """
    return _AGENTS_JS.read_text(encoding="utf-8")


def _render_html(tmp_path: Path) -> str:
    """Render an empty dashboard and return its HTML.

    Args:
        tmp_path: Pytest-managed temporary directory.

    Returns:
        The complete rendered dashboard HTML.
    """
    output_path = tmp_path / "dashboard.html"
    render(AggregateResult(), output_path=output_path, open_browser=False)
    return output_path.read_text(encoding="utf-8")


def _extract_render_view_body(html: str) -> str:
    """Extract the dashboard shell's view-dispatch function.

    Args:
        html: Complete rendered dashboard HTML.

    Returns:
        JavaScript source for ``_renderView``.
    """
    start = html.index("function _renderView(view)")
    end = html.index("function setView(view)", start)
    return html[start:end]


def test_agent_view_exposes_render_entry_point() -> None:
    """Removing the shell-callable view renderer must fail the suite."""
    source = _read_agents_js_source()

    assert "window.renderAgents" in source


def test_shared_agent_helpers_are_exported() -> None:
    """Removing a shared escaping or path helper must fail the suite."""
    source = _CP_UTILS_JS.read_text(encoding="utf-8")

    assert "const AGENT_PATH_SEP = '→';" in source
    assert "function esc(" in source
    assert "function agentLeaf(" in source
    assert "AGENT_PATH_SEP," in source
    assert "esc," in source
    assert "agentLeaf," in source


def test_existing_views_consume_shared_helpers() -> None:
    """Reintroducing private helper copies must fail the suite."""
    economics_source = _ECONOMICS_JS.read_text(encoding="utf-8")
    mcp_source = _MCP_USAGE_JS.read_text(encoding="utf-8")

    assert "function agentLeaf(" not in economics_source
    assert "CP.agentLeaf(" in economics_source
    assert "function esc(" not in mcp_source
    assert "const esc = CP.esc;" in mcp_source


def test_shared_name_filter_helper_is_exported_and_consumed() -> None:
    """Both dashboard consumers must use the shared name-filter helper."""
    cp_source = _CP_UTILS_JS.read_text(encoding="utf-8")
    agents_source = _read_agents_js_source()
    mcp_source = _MCP_USAGE_JS.read_text(encoding="utf-8")

    assert "function matchesNameFilter(name, query)" in cp_source
    assert "matchesNameFilter," in cp_source
    assert "function matchesAgentFilter(" not in agents_source
    assert "function matchesNameFilter(" not in mcp_source
    assert "CP.matchesNameFilter(" in agents_source
    assert "CP.matchesNameFilter(" in mcp_source


def test_agent_filter_has_accessible_control_and_scoped_results() -> None:
    """Removing the accessible filter or scoped result target must fail."""
    source = _read_agents_js_source()

    assert 'id="agent-name-filter"' in source
    assert "aria-label=" in source
    assert "parent" in source.lower()
    assert 'id="agent-result-list"' in source
    assert 'aria-live="polite"' in source


def test_input_listener_preserves_filter_focus() -> None:
    """Replacing the whole view while typing must fail the suite."""
    source = _read_agents_js_source()
    listener = re.search(
        r"agent-name-filter.*?addEventListener\(\s*['\"]input['\"]"
        r"(?P<body>.*?)\n\s*\}\);",
        source,
        re.DOTALL,
    )

    assert listener is not None
    body = listener.group("body")
    assert ".value" in body
    assert "agent-result-list" in source
    assert "root.innerHTML" not in body


def test_agent_view_supports_every_approved_period() -> None:
    """Dropping an approved period or filtered re-aggregation must fail."""
    source = _read_agents_js_source()

    for period in ("5h", "24h", "7d", "30d", "all"):
        assert f"'{period}'" in source
    assert "CP.reAggregateAgents(" in source
    assert "window.DATA.sessions, period, window.DATA.by_agent" in re.sub(
        r"\s+", " ", source
    )
    assert "window.DATA.by_agent" in source


def test_agent_rows_include_the_complete_metric_contract() -> None:
    """Dropping an issue-required agent metric must fail the suite."""
    source = _read_agents_js_source()

    for field in (
        "primary_model",
        "total_tokens",
        "message_count",
        "session_count",
        "cache_creation_tokens",
        "cache_read_tokens",
    ):
        assert field in source
    assert "CP.agentLeaf(" in source
    assert "CP.esc(" in source


def test_agent_view_includes_general_and_has_empty_state() -> None:
    """Hiding root context or matched-empty guidance must fail the suite."""
    source = _read_agents_js_source()

    assert "root session context" in source.lower()
    assert "no agents match" in source.lower()
    assert "name !== 'general'" not in source


def test_agent_view_reports_match_count() -> None:
    """Hiding broad parent-query result counts must fail the suite."""
    source = _read_agents_js_source()

    assert 'id="agent-match-count"' in source
    assert "rows.length" in source


def test_reaggregate_populates_period_aware_agent_metrics() -> None:
    """Dropping period-aware agent row fields must fail the suite."""
    source = _CP_UTILS_JS.read_text(encoding="utf-8")
    reaggregate = source[source.index("function reAggregate(") :]

    for field in (
        "message_count",
        "cache_creation_tokens",
        "cache_read_tokens",
    ):
        assert f"byAgent[agent].{field} +=" in reaggregate
    assert "s.agent_stats" in reaggregate
    assert "exact.message_count" in reaggregate
    assert "exact.cache_creation_tokens" in reaggregate
    assert "exact.cache_read_tokens" in reaggregate
    assert "Object.entries(exact.model_split" in reaggregate


def test_reaggregate_selects_primary_model_by_message_count(tmp_path: Path) -> None:
    """Bounded and all-time periods must use the same primary-model rule."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; JavaScript execution test skipped")

    runner = tmp_path / "reaggregate-check.js"
    runner.write_text(
        """
const fs = require('fs');
const vm = require('vm');
global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'));
const sessions = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
process.stdout.write(JSON.stringify(window.CP.reAggregate(sessions).byAgent));
""",
        encoding="utf-8",
    )
    sessions_path = tmp_path / "sessions.json"
    sessions_path.write_text(
        json.dumps(
            [
                {
                    "session_id": "s1",
                    "project": "proj",
                    "start_time": "2026-09-05T12:00:00+00:00",
                    "total_tokens": 2000,
                    "model_split": {"sonnet": 1000, "opus": 1000},
                    "agent_stats": {
                        "general": {
                            "total_tokens": 2000,
                            "message_count": 11,
                            "cache_creation_tokens": 0,
                            "cache_read_tokens": 0,
                            "model_split": {"sonnet": 500, "opus": 1500},
                            "model_message_counts": {"sonnet": 10, "opus": 1},
                        }
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [node, str(runner), str(_CP_UTILS_JS), str(sessions_path)],
        capture_output=True,
        check=True,
        text=True,
    )
    by_agent = json.loads(completed.stdout)

    assert by_agent["general"]["primary_model"] == "sonnet"


def test_bounded_agent_period_keeps_activity_after_session_start(
    tmp_path: Path,
) -> None:
    """A session starting before the cutoff must retain later agent messages."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; JavaScript execution test skipped")

    runner = tmp_path / "bounded-agent-check.js"
    runner.write_text(
        """
const fs = require('fs');
const vm = require('vm');
global.window = { MOCK_NOW: new Date('2026-09-05T12:00:00+00:00') };
vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'));
const sessions = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const byAgent = window.CP.reAggregateAgents
  ? window.CP.reAggregateAgents(sessions, '5h').byAgent
  : window.CP.reAggregate(window.CP.filterSessions(sessions, '5h')).byAgent;
process.stdout.write(JSON.stringify(byAgent));
""",
        encoding="utf-8",
    )
    sessions_path = tmp_path / "bounded-agent-sessions.json"
    sessions_path.write_text(
        json.dumps(
            [
                {
                    "session_id": "spans-cutoff",
                    "project": "proj",
                    "start_time": "2026-09-05T06:00:00+00:00",
                    "total_tokens": 1250,
                    "message_count": 4,
                    "model_split": {"haiku": 50, "opus": 1000, "sonnet": 200},
                    "agent_stats": {
                        "general": {
                            "total_tokens": 1250,
                            "message_count": 4,
                            "cache_creation_tokens": 36,
                            "cache_read_tokens": 57,
                            "model_split": {
                                "haiku": 50,
                                "opus": 1000,
                                "sonnet": 200,
                            },
                            "model_message_counts": {
                                "haiku": 1,
                                "opus": 1,
                                "sonnet": 2,
                            },
                        }
                    },
                    "agent_activity": [
                        {
                            "timestamp": "2026-09-05T06:00:00+00:00",
                            "agent": "general",
                            "model": "haiku",
                            "total_tokens": 50,
                            "cache_creation_tokens": 1,
                            "cache_read_tokens": 2,
                        },
                        {
                            "timestamp": "2026-09-05T08:00:00+00:00",
                            "agent": "general",
                            "model": "opus",
                            "total_tokens": 1000,
                            "cache_creation_tokens": 20,
                            "cache_read_tokens": 40,
                        },
                        {
                            "timestamp": "2026-09-05T10:00:00+00:00",
                            "agent": "general",
                            "model": "sonnet",
                            "total_tokens": 100,
                            "cache_creation_tokens": 10,
                            "cache_read_tokens": 10,
                        },
                        {
                            "timestamp": "2026-09-05T11:00:00+00:00",
                            "agent": "general",
                            "model": "sonnet",
                            "total_tokens": 100,
                            "cache_creation_tokens": 5,
                            "cache_read_tokens": 5,
                        },
                    ],
                },
                {
                    "session_id": "legacy-in-window",
                    "project": "proj",
                    "start_time": "2026-09-05T09:00:00+00:00",
                    "total_tokens": 75,
                    "message_count": 1,
                    "model_split": {"haiku": 75},
                    "agent_tokens": {"legacy-agent": 75},
                    "agent_stats": {
                        "legacy-agent": {
                            "total_tokens": 75,
                            "message_count": 1,
                            "cache_creation_tokens": 3,
                            "cache_read_tokens": 4,
                            "model_split": {"haiku": 75},
                            "model_message_counts": {"haiku": 1},
                        }
                    },
                },
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [node, str(runner), str(_CP_UTILS_JS), str(sessions_path)],
        capture_output=True,
        check=True,
        text=True,
    )
    by_agent = json.loads(completed.stdout)

    assert by_agent["general"] == {
        "total_tokens": 1200,
        "message_count": 3,
        "session_count": 1,
        "cache_creation_tokens": 35,
        "cache_read_tokens": 55,
        "primary_model": "sonnet",
        "_modelCounts": {"opus": 1, "sonnet": 2},
        "_modelTokens": {"opus": 1000, "sonnet": 200},
    }
    assert by_agent["legacy-agent"]["total_tokens"] == 75
    assert by_agent["legacy-agent"]["primary_model"] == "haiku"


def test_agents_tab_is_inlined_and_wired(tmp_path: Path) -> None:
    """Removing any shell entry point for Agents must fail the suite."""
    html = _render_html(tmp_path)

    assert 'data-view="agents"' in html
    assert "window.renderAgents" in html
    assert "agents:" in html


def test_view_dispatch_is_exhaustive_and_rejects_unknown_views(
    tmp_path: Path,
) -> None:
    """Restoring Advanced as the unknown-view catch-all must fail."""
    html = _render_html(tmp_path)
    body = _extract_render_view_body(html)
    view_names = set(re.findall(r'data-view="([^"]+)"', html))

    assert view_names == {"basic", "detail", "advanced", "mcp", "agents"}
    for view_name in view_names:
        assert re.search(
            rf"view\s*===\s*['\"]{view_name}['\"]",
            body,
        )
    assert "renderAgents(_container)" in body
    assert re.search(
        r"view\s*===\s*['\"]advanced['\"].*?renderEconomics\(_container\)",
        body,
        re.DOTALL,
    )
    assert "console.error('Unknown view:', view)" in body


def test_view_tabs_scroll_inside_narrow_viewports(tmp_path: Path) -> None:
    """Restoring page-level horizontal overflow must fail the suite."""
    html = _render_html(tmp_path)
    rule = re.search(r"\.view-toggle\s*\{(?P<body>.*?)\}", html, re.DOTALL)

    assert rule is not None
    body = rule.group("body")
    assert "max-width: 100%" in body
    assert "overflow-x: auto" in body


def test_view_tabs_support_keyboard_navigation(tmp_path: Path) -> None:
    """ARIA tabs must support roving focus and standard navigation keys."""
    html = _render_html(tmp_path)

    assert 'role="tablist"' in html
    assert 'tabindex="0"' in html
    assert 'tabindex="-1"' in html
    assert "addEventListener('keydown'" in html
    for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"):
        assert key in html
