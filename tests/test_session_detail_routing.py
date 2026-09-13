"""Coverage for hash-routed dashboard session navigation."""

from importlib import resources
from pathlib import Path

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_view(name: str) -> str:
    """Return a packaged dashboard view's source."""
    return (
        _REPO_ROOT / "src" / "claude_prospector" / "static" / "views" / name
    ).read_text(encoding="utf-8")


def _render_html(tmp_path: Path) -> str:
    """Render a minimal dashboard and return its inlined HTML."""
    output = tmp_path / "dashboard.html"
    render(AggregateResult(), output_path=output, open_browser=False)
    return output.read_text(encoding="utf-8")


def test_both_session_lists_dispatch_open_session() -> None:
    """Session lists expose encoded native links that open session routes."""
    basic = _read_view("economics-basic.js")
    detail = _read_view("layout-b-diag.js")

    assert "economy:open-session" in basic
    assert "economy:open-session" in detail
    assert "encodeURIComponent(String(s.session_id" in basic
    assert "encodeURIComponent(String(s.session_id" in detail
    assert 'href="#session=${encodedSessionId}"' in basic
    assert 'href="#session=${encodedSessionId}"' in detail


def test_shell_handles_direct_hash_back_and_unknown_session(tmp_path: Path) -> None:
    """The rendered shell routes direct hashes and browser navigation."""
    html = _render_html(tmp_path)

    assert "history.pushState" in html
    assert "popstate" in html
    assert "hashchange" in html
    assert "Session not found in this dashboard" in html


def test_minimal_session_view_is_packaged_and_inlined(tmp_path: Path) -> None:
    """The detail lifecycle is packaged and embedded in the dashboard."""
    asset = (
        resources.files("claude_prospector") / "static" / "views" / "session-detail.js"
    )

    assert asset.is_file()
    assert "function renderSessionDetail" in _render_html(tmp_path)
