"""Tests for .claude-plugin/plugin.json schema correctness.

Regression guards for issue #149 and related manifest field requirements.
These tests load the raw JSON so that structural edits to plugin.json are
caught immediately, without requiring an installed package.
"""

from __future__ import annotations

import json
from pathlib import Path

# Resolve the repo root relative to this test file's location.
# Layout: tests/unit/test_plugin_manifest.py  ->  repo-root/.claude-plugin/
_REPO_ROOT = Path(__file__).parent.parent.parent
_PLUGIN_JSON = _REPO_ROOT / ".claude-plugin" / "plugin.json"


def _load_plugin_json() -> dict:
    """Load and parse .claude-plugin/plugin.json.

    Returns:
        Parsed JSON content as a dict.

    Raises:
        FileNotFoundError: If plugin.json is missing from the repo root.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    return json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))


def test_autoregen_default_is_false() -> None:
    """userConfig.autoregen must carry an explicit ``default: false`` field.

    Regression guard for issue #149.  Without this field the Claude Code
    plugin manager has no schema-declared default and may behave differently
    across installations (e.g. treating a missing value as true, or
    prompting on every install).  The default must be the boolean ``False``,
    not the integer ``0`` or the string ``"false"`` — hence ``is False``
    rather than ``== False`` to catch type drift.
    """
    data = _load_plugin_json()
    autoregen = data["userConfig"]["autoregen"]
    assert "default" in autoregen, (
        "userConfig.autoregen is missing a 'default' key in plugin.json. "
        'Add `"default": false` to fix issue #149.'
    )
    assert autoregen["default"] is False, (
        f"userConfig.autoregen.default must be the boolean False, "
        f"got {autoregen['default']!r} (type {type(autoregen['default']).__name__}). "
        "Ensure the value is JSON `false`, not 0 or \"false\"."
    )
