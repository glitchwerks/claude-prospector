"""Tests that the dashboard template is accessible via importlib.resources.

These tests are the regression gate for issue #138: the 0.8.0 wheel shipped
without ``templates/dashboard.html`` because ``[tool.setuptools.package-data]``
was missing.  The loader in ``renderer.py`` used ``FileSystemLoader`` with a
``Path(__file__).parent``-relative path, which works in an editable install
(working tree has the file) but fails in a wheel install where the filesystem
path is ``<venv>/Lib/site-packages/templates/`` — outside the package.

The fix is to use ``importlib.resources`` so the loader resolves the template
through Python's package resource system, which works identically for both
editable and wheel installs.
"""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path

import pytest

from claude_prospector.aggregator import AggregateResult
from claude_prospector.renderer import render


@pytest.mark.parametrize(
    "name,session_id,total,path_count",
    [
        ("short-single-agent", "short", 60, 1),
        ("long-concurrent-agents", "long-concurrent", 1000, 3),
        ("deep-nested-agents", "deep", 5, 5),
    ],
)
def test_session_fixtures_render_with_packaged_detail_resource(
    tmp_path: Path, name: str, session_id: str, total: int, path_count: int
) -> None:
    """Missing client fixtures or omitted session resources break rendering.

    Fixtures are repository test data; the view is an installed package
    resource and must be inlined for generated reports to work offline.

    Args:
        tmp_path: Temporary output directory.
        name: Committed fixture filename without extension.
        session_id: Expected session identifier.
        total: Hand-checked response token total.
        path_count: Number of independently selectable agent paths.
    """
    fixture = Path(__file__).parent / "fixtures" / "session-analytics" / f"{name}.json"
    session = json.loads(fixture.read_text(encoding="utf-8"))
    assert session["session_id"] == session_id
    assert session["total_tokens"] == total
    assert sum(row["total_tokens"] for row in session["agent_activity"]) == total
    assert len(session["agent_paths"]) == path_count
    package = importlib.resources.files("claude_prospector")
    asset = package / "static" / "views" / "session-detail.js"
    assert asset.is_file()
    source = asset.read_text(encoding="utf-8")
    assert source.strip()
    output = render(
        AggregateResult(sessions=[session]),
        tmp_path / f"{name}.html",
        open_browser=False,
    )
    html = output.read_text(encoding="utf-8")
    assert f"<script>{source}</script>" in html
    assert f'"session_id": "{session_id}"' in html


def test_dashboard_template_accessible_via_importlib_resources() -> None:
    """importlib.resources can locate templates/dashboard.html.

    This is the canonical test for issue #138.  If the template is absent
    from the installed wheel (missing package-data declaration) or the loader
    resolves the wrong path, ``files()`` will either raise or return a
    non-file traversable, and the assertion will fail.

    This test passes for both editable installs (working-tree file) and
    real wheel installs (zip-extracted or lazy-loaded by importlib).
    """
    pkg = importlib.resources.files("claude_prospector")
    template = pkg / "templates" / "dashboard.html"

    # The traversable must be a file, not a directory or missing entry.
    assert template.is_file(), (
        "templates/dashboard.html is not accessible via "
        "importlib.resources.files('claude_prospector'). "
        "This means the package-data declaration is missing or the "
        "template was not included in the installed wheel. "
        f"Resolved path hint: {template!r}"
    )


def test_dashboard_template_is_non_empty() -> None:
    """templates/dashboard.html has non-zero content.

    Guards against an accidentally empty or stub template being shipped.
    The real template is ~70 KB; requiring at least 1000 bytes is a
    loose lower bound that would catch a zero-byte placeholder.
    """
    pkg = importlib.resources.files("claude_prospector")
    template = pkg / "templates" / "dashboard.html"

    content = template.read_bytes()
    assert len(content) >= 1000, (
        f"templates/dashboard.html is suspiciously small "
        f"({len(content)} bytes); expected at least 1000 bytes."
    )


def test_renderer_uses_importlib_resources_loader() -> None:
    """renderer.py must not use FileSystemLoader with a __file__-relative path.

    ``FileSystemLoader`` with ``Path(__file__).parent / 'templates'`` works
    in a source checkout (editable install) but breaks in a wheel install
    when the package is installed into site-packages and the templates
    directory is not on the filesystem at all (zipimport / zipapp).

    This test inspects the renderer module source to ensure the old pattern
    is absent.  It is a documentation-level test — it breaks if someone
    re-introduces the fragile pattern during a future refactor.
    """
    import inspect

    import claude_prospector.renderer as renderer_module

    source = inspect.getsource(renderer_module)

    # The old fragile pattern: FileSystemLoader(str(_TEMPLATE_DIR))
    # combined with _TEMPLATE_DIR derived from Path(__file__)
    assert "FileSystemLoader" not in source, (
        "renderer.py still uses FileSystemLoader. "
        "Switch to PackageLoader('claude_prospector', 'templates') "
        "or importlib.resources so the template resolves correctly in "
        "both editable and wheel installs (issue #138)."
    )
