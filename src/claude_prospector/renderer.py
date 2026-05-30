"""Render aggregated data as a self-contained HTML dashboard."""

from __future__ import annotations

import importlib.resources
import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from jinja2 import Environment, PackageLoader

from claude_prospector.aggregator import AggregateResult


def _read_static(relative_path: str) -> str:
    """Read a static asset from the package using importlib.resources.

    Uses ``importlib.resources.files()`` so the file resolves correctly
    in both editable source-tree installs and built wheel installs.

    Args:
        relative_path: Path relative to the ``static/`` directory inside
            the ``claude_prospector`` package, using forward slashes
            (e.g. ``"vendor/chart.umd.min.js"``).

    Returns:
        The file contents as a UTF-8 string.

    Raises:
        FileNotFoundError: If the static asset is not present in the
            installed package.
    """
    pkg = importlib.resources.files("claude_prospector")
    # Navigate through path components so the traversal works on both
    # editable installs (real filesystem) and wheel installs (zipimport).
    resource = pkg / "static"
    for part in relative_path.split("/"):
        resource = resource / part  # type: ignore[operator]

    if not resource.is_file():
        raise FileNotFoundError(
            f"Static asset not found in package: static/{relative_path}. "
            "Check that [tool.setuptools.package-data] includes "
            "'static/**/*' in pyproject.toml."
        )
    return resource.read_text(encoding="utf-8")


def render(
    result: AggregateResult,
    output_path: Path | None = None,
    open_browser: bool = True,
    limits: dict[str, int] | None = None,
) -> Path:
    """Render the dashboard HTML from aggregated data.

    Uses ``jinja2.PackageLoader`` so the template resolves via Python's
    package resource system (``importlib.resources``) rather than a
    ``Path(__file__)``-relative filesystem lookup.  This makes the loader
    work identically for both editable source-tree installs and built
    wheel installs, fixing the ``TemplateNotFound`` crash reported in
    issue #138.

    Static assets (Chart.js, chartjs-chart-treemap, cp-utils) are read
    via ``importlib.resources`` and inlined into the HTML so the output
    is a fully self-contained, offline-capable file.

    Args:
        result: Aggregated usage data.
        output_path: Where to write the HTML. If None, writes to a temp
            file.
        open_browser: Whether to open the result in the default browser.
        limits: Optional budget limits:
            {limit_5h, limit_7d, limit_sonnet_7d}.

    Returns:
        Path to the generated HTML file.
    """
    env = Environment(
        loader=PackageLoader("claude_prospector", "templates"),
        autoescape=True,
    )
    template = env.get_template("dashboard.html")

    data = {
        "total_tokens": result.total_tokens,
        "total_messages": result.total_messages,
        "total_sessions": result.total_sessions,
        "by_model": result.by_model,
        "by_agent": result.by_agent,
        "by_skill": result.by_skill,
        "by_skill_adoption": result.by_skill_adoption,
        "by_project": result.by_project,
        "by_day": result.by_day,
        "sessions": result.sessions,
    }

    html = template.render(
        data_json=json.dumps(data, indent=2, default=str),
        generated_at=datetime.now(timezone.utc).isoformat(),
        limits_json=json.dumps(limits) if limits else "null",
        chart_js=_read_static("vendor/chart.umd.min.js"),
        treemap_js=_read_static("vendor/chartjs-chart-treemap.min.js"),
        cp_utils_js=_read_static("cp-utils.js"),
        economics_basic_js=_read_static("views/economics-basic.js"),
        layout_b_diag_js=_read_static("views/layout-b-diag.js"),
        economics_js=_read_static("views/economics.js"),
    )

    if output_path is None:
        tmp = NamedTemporaryFile(
            suffix=".html",
            prefix="claude-prospector-",
            delete=False,
            mode="w",
            encoding="utf-8",
        )
        tmp.write(html)
        tmp.close()
        output_path = Path(tmp.name)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    if open_browser:
        webbrowser.open(output_path.as_uri())

    return output_path
