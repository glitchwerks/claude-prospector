"""Packaging smoke tests; interactive behavior runs in the Node VM suite."""

from importlib import resources
from pathlib import Path

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render


def _session_result() -> AggregateResult:
    """Return an aggregate containing one exact session response."""
    result = AggregateResult(total_tokens=10, total_messages=1, total_sessions=1)
    result.sessions = [
        {
            "session_id": "session-1",
            "project": "project",
            "project_path": "/project",
            "start_time": "2026-09-13T10:00:00+00:00",
            "end_time": "2026-09-13T10:01:00+00:00",
            "duration_seconds": 60,
            "root_agent": "main",
            "agent_paths": [["main"]],
            "agent_activity": [
                {
                    "timestamp": "2026-09-13T10:00:00+00:00",
                    "agent": "main",
                    "agent_path": ["main"],
                    "model": "sonnet",
                    "model_full": "claude-sonnet-5",
                    "effort": "high",
                    "effort_key": "high",
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "cache_read_tokens": 3,
                    "cache_creation_tokens": 4,
                    "total_tokens": 10,
                }
            ],
            "skill_activity": [],
            "command_activity": [],
            "session_facts": {"metadata": [], "effort_conflicts": 0},
            "mcp_collection": {
                "calls": "not_collected",
                "result_sizes": "not_collected",
            },
            "mcp_activity": None,
        }
    ]
    return result


def _render_html(tmp_path: Path, result: AggregateResult | None = None) -> str:
    """Render the supplied aggregate to an inlined dashboard.

    Args:
        tmp_path: Isolated output directory.
        result: Optional session aggregate.

    Returns:
        Self-contained dashboard HTML.
    """
    output = tmp_path / "dashboard.html"
    render(result or AggregateResult(), output_path=output, open_browser=False)
    return output.read_text(encoding="utf-8")


def test_session_controls_ship_in_rendered_dashboard(tmp_path: Path) -> None:
    """The packaged session asset and semantic controls reach rendered HTML."""
    source = (
        resources.files("claude_prospector") / "static" / "views" / "session-detail.js"
    ).read_text(encoding="utf-8")
    html = _render_html(tmp_path, _session_result())
    assert source in html
    for hook in (
        "Session analytics scope",
        "['all', 'period']",
        "setAttribute('role', 'tree')",
        "indeterminate",
        "No agents selected",
    ):
        assert hook in source


def test_empty_dashboard_retains_session_renderer(tmp_path: Path) -> None:
    """No sessions still produces a dashboard with its route view installed."""
    assert "window.renderSessionDetail = renderSessionDetail" in _render_html(tmp_path)
