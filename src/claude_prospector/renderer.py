"""Render aggregated data as a self-contained HTML dashboard."""

from __future__ import annotations

import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from jinja2 import Environment, PackageLoader

from claude_prospector.aggregator import AggregateResult


def render(
    result: AggregateResult,
    output_path: Path | None = None,
    open_browser: bool = True,
    limits: dict[str, int] | None = None,
    dry_run: bool = False,
) -> Path | None:
    """Render the dashboard HTML from aggregated data.

    Uses ``jinja2.PackageLoader`` so the template resolves via Python's
    package resource system (``importlib.resources``) rather than a
    ``Path(__file__)``-relative filesystem lookup.  This makes the loader
    work identically for both editable source-tree installs and built
    wheel installs, fixing the ``TemplateNotFound`` crash reported in
    issue #138.

    Args:
        result: Aggregated usage data.
        output_path: Where to write the HTML. If None, writes to a temp
            file. Ignored when ``dry_run`` is True.
        open_browser: Whether to open the result in the default browser.
            Ignored when ``dry_run`` is True.
        limits: Optional budget limits:
            {limit_5h, limit_7d, limit_sonnet_7d}.
        dry_run: When True, write the rendered HTML to ``sys.stdout``
            instead of a file and do not open the browser. Returns None.

    Returns:
        Path to the generated HTML file, or None when ``dry_run`` is
        True.
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
    )

    if dry_run:
        sys.stdout.buffer.write(html.encode("utf-8"))
        return None

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
        output_path.write_text(html, encoding="utf-8")

    if open_browser:
        webbrowser.open(output_path.as_uri())

    return output_path
