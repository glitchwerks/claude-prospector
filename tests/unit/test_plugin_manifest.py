"""Tests for .claude-plugin/plugin.json and hooks/hooks.json schema
correctness.

Regression guards for issue #149 and issue #236, and related manifest
field requirements. These tests load the raw JSON so that structural
edits to plugin.json / hooks.json are caught immediately, without
requiring an installed package.
"""

from __future__ import annotations

import json
from pathlib import Path

# Resolve the repo root relative to this test file's location.
# Layout: tests/unit/test_plugin_manifest.py  ->  repo-root/.claude-plugin/
_REPO_ROOT = Path(__file__).parent.parent.parent
_PLUGIN_JSON = _REPO_ROOT / ".claude-plugin" / "plugin.json"
_HOOKS_JSON = _REPO_ROOT / "hooks" / "hooks.json"


def _load_plugin_json() -> dict:
    """Load and parse .claude-plugin/plugin.json.

    Returns:
        Parsed JSON content as a dict.

    Raises:
        FileNotFoundError: If plugin.json is missing from the repo root.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    return json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))


def _load_hooks_json() -> dict:
    """Load and parse hooks/hooks.json.

    Returns:
        Parsed JSON content as a dict.

    Raises:
        FileNotFoundError: If hooks.json is missing from the repo root.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    return json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))


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


def test_stop_hook_dashboard_regen_uses_exec_form() -> None:
    """The Stop hook's dashboard-regen entry must use exec form, not
    shell form, when referencing ``${user_config.*}``.

    Regression guard for issue #236. Claude Code (v2.1.207+) rejects a
    shell-form hook `command` that embeds `${user_config.*}` because the
    substituted value would be re-parsed by the shell:

        Stop hook error: Failed to run: Hook from plugin
        claude-prospector@glitchwerks references ${user_config.*} in a
        shell-form command...

    Exec form sidesteps this entirely: `${user_config.*}` values are
    substituted as plain strings into `command` and each `args` element,
    with no shell involved. Exec form is triggered by the presence of an
    `args` array, with `command` reduced to the bare executable name.
    """
    data = _load_hooks_json()

    stop_entry = None
    for group in data["hooks"]["Stop"]:
        for entry in group.get("hooks", []):
            haystack = list(entry.get("args", [])) + [entry.get("command", "")]
            if any("dashboard-regen.py" in str(item) for item in haystack):
                stop_entry = entry
                break
        if stop_entry is not None:
            break

    assert stop_entry is not None, (
        "Could not find a Stop hook entry referencing "
        "'dashboard-regen.py' in hooks/hooks.json's 'Stop' hooks. "
        "Searched all hook groups and entries under data['hooks']['Stop']."
    )

    assert "args" in stop_entry, (
        "Stop hook's dashboard-regen entry has no 'args' key, so it is "
        "still shell form. Convert to exec form: "
        '{"command": "python", "args": [...]}.'
    )
    assert isinstance(stop_entry["args"], list), (
        f"Stop hook's 'args' must be a list, got "
        f"{type(stop_entry['args']).__name__}."
    )

    command = stop_entry["command"]
    assert "${user_config" not in command, (
        f"Stop hook's 'command' still embeds '${{user_config...}}': "
        f"{command!r}. In exec form, 'command' must be the bare "
        'executable name (e.g. "python") with all arguments — '
        "including ${user_config.*} substitutions — moved to 'args'."
    )
    assert command == "python", (
        f"Stop hook's 'command' must be the bare executable name "
        f"'python' in exec form, got {command!r}."
    )

    args = stop_entry["args"]
    expected_args = [
        "${CLAUDE_PLUGIN_ROOT}/hooks/dashboard-regen.py",
        "--autoregen",
        "${user_config.autoregen}",
    ]
    assert args == expected_args, (
        "Stop hook's 'args' must be exactly "
        f"{expected_args!r} (script path, then '--autoregen', then its "
        f"value, in that order — unquoted, since exec-form args are "
        f"passed literally with no shell quoting needed). Got args: "
        f"{args!r}."
    )
