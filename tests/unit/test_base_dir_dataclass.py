"""Unit tests for the BaseDirResolution dataclass in hooks/dashboard-regen.py.

Tests the three-tier resolution of _base_dir() via importlib so no
changes to sys.path are required for package-level code.

Resolution priority (highest first):
    1. CLAUDE_PROSPECTOR_BASE_DIR  — explicit test/override path.
    2. CLAUDE_PLUGIN_DATA          — Anthropic plugin state dir.
    3. Legacy ~/.claude/claude-prospector/ fallback.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import hook module via importlib (lives outside src/, not a package).
# ---------------------------------------------------------------------------
_WORKTREE = Path(__file__).parent.parent.parent
_HOOK_PATH = _WORKTREE / "hooks" / "dashboard-regen.py"


def _load_hook_module():
    """Load hooks/dashboard-regen.py as a module without executing main().

    Returns:
        The loaded module object.
    """
    # Ensure hooks/lib is importable so setup_state (imported at module level
    # in the hook) can be found.
    hooks_lib = str(_WORKTREE / "hooks" / "lib")
    if hooks_lib not in sys.path:
        sys.path.insert(0, hooks_lib)

    spec = importlib.util.spec_from_file_location("dashboard_regen_hook", _HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass decorator can resolve __module__.
    sys.modules["dashboard_regen_hook"] = module
    spec.loader.exec_module(module)
    return module


# Load once at collection time.
_hook = _load_hook_module()


# ---------------------------------------------------------------------------
# Tests for BaseDirResolution and _base_dir()
# ---------------------------------------------------------------------------


class TestBaseDirResolution:
    """BaseDirResolution is a frozen dataclass with a single ``path`` field."""

    def test_is_dataclass_with_path_field(self) -> None:
        """BaseDirResolution has a ``path`` attribute of type Path."""
        import dataclasses

        assert dataclasses.is_dataclass(_hook.BaseDirResolution)
        fields = {f.name: f for f in dataclasses.fields(_hook.BaseDirResolution)}
        assert "path" in fields
        assert fields["path"].type is Path or fields["path"].type == "Path"

    def test_is_frozen(self) -> None:
        """BaseDirResolution instances are immutable (frozen=True)."""
        import dataclasses

        # frozen dataclasses raise FrozenInstanceError on attribute assignment
        instance = _hook.BaseDirResolution(path=Path("/some/path"))
        with pytest.raises(
            (dataclasses.FrozenInstanceError, TypeError, AttributeError)
        ):
            instance.path = Path("/other/path")  # type: ignore[misc]


class TestBaseDirEnvOverride:
    """When CLAUDE_PROSPECTOR_BASE_DIR is set it takes priority."""

    def test_env_override_returns_that_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_BASE_DIR set → BaseDirResolution.path equals it."""
        monkeypatch.setenv("CLAUDE_PROSPECTOR_BASE_DIR", str(tmp_path))
        monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)

        result = _hook._base_dir()

        assert isinstance(result, _hook.BaseDirResolution)
        assert result.path == tmp_path

    def test_env_override_takes_priority_over_plugin_data(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PROSPECTOR_BASE_DIR wins even when CLAUDE_PLUGIN_DATA is set."""
        override_path = tmp_path / "override"
        plugin_path = tmp_path / "plugin"
        monkeypatch.setenv("CLAUDE_PROSPECTOR_BASE_DIR", str(override_path))
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_path))

        result = _hook._base_dir()

        assert result.path == override_path


class TestBaseDirPluginData:
    """When CLAUDE_PROSPECTOR_BASE_DIR is unset, CLAUDE_PLUGIN_DATA is used."""

    def test_plugin_data_used_when_override_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLAUDE_PLUGIN_DATA set → BaseDirResolution.path equals it."""
        monkeypatch.delenv("CLAUDE_PROSPECTOR_BASE_DIR", raising=False)
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))

        result = _hook._base_dir()

        assert isinstance(result, _hook.BaseDirResolution)
        assert result.path == tmp_path


class TestBaseDirLegacyDefault:
    """When both env vars are unset the legacy ~/.claude/claude-prospector/ is used."""

    def test_legacy_default_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both vars unset → BaseDirResolution.path is ~/.claude/claude-prospector/."""
        monkeypatch.delenv("CLAUDE_PROSPECTOR_BASE_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)

        result = _hook._base_dir()

        assert isinstance(result, _hook.BaseDirResolution)
        expected = Path.home() / ".claude" / "claude-prospector"
        assert result.path == expected
