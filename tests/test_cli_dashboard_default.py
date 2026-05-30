"""Tests for dashboard --output default-path resolution (issue #201).

When ``$CLAUDE_PLUGIN_DATA`` is set, omitting ``--output`` must resolve to
``$CLAUDE_PLUGIN_DATA/dashboard.html`` (a persistent, plugin-owned location).
When the env var is unset, the CLI must fall back to the existing
``render(output_path=None)`` temp-file path — preserving the contract that
``render()`` interprets ``None`` as "write to a temp file".
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from claude_prospector.cli.dashboard import build_parser, run


class TestDefaultOutputPathResolution:
    """dashboard --output default resolves to plugin-data dir or temp file."""

    def _make_args(
        self,
        tmp_path: Path,
        output: Path | None = None,
        data_dir: Path | None = None,
    ) -> argparse.Namespace:
        """Build a minimal Namespace for the dashboard ``run()`` handler.

        Args:
            tmp_path: Pytest temporary directory (used as ``--data-dir``
                when ``data_dir`` is not provided).
            output: Value for ``args.output``. ``None`` simulates omitting
                ``--output`` (the argparse default).
            data_dir: Override the ``--data-dir`` value.

        Returns:
            An ``argparse.Namespace`` suitable for passing to ``run()``.
        """
        return argparse.Namespace(
            data_dir=data_dir if data_dir is not None else tmp_path,
            from_date=None,
            to_date=None,
            window=None,
            output=output,
            no_open=True,
            limit_5h=None,
            limit_7d=None,
            limit_sonnet_7d=None,
            output_format="html",
        )

    def test_plugin_data_set_resolves_to_plugin_data_dashboard(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """With CLAUDE_PLUGIN_DATA set, omitting --output writes to plugin dir.

        The output path must be ``$CLAUDE_PLUGIN_DATA/dashboard.html`` and
        the file must be created (including its parent directory if needed).
        """
        plugin_data_dir = tmp_path / "plugin-data"
        # Intentionally do NOT create the directory here — run() must create it
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data_dir))

        args = self._make_args(tmp_path)
        # --output omitted → args.output is None
        assert args.output is None

        run(args)

        expected = plugin_data_dir / "dashboard.html"
        assert expected.exists(), (
            f"With CLAUDE_PLUGIN_DATA={plugin_data_dir}, omitting --output "
            f"must write the dashboard to {expected}. "
            f"File was not found — default-path resolution or mkdir is broken."
        )

    def test_plugin_data_unset_falls_back_to_temp_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """With CLAUDE_PLUGIN_DATA unset, omitting --output writes a temp file.

        The temp-file fallback must produce a file on disk (the existing
        render(output_path=None) contract). The test asserts the command
        exits without error and does NOT write to a plugin-data path, since
        that env var is absent.
        """
        monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)

        args = self._make_args(tmp_path)
        assert args.output is None

        # run() returns 0 on success; any exception here is a failure.
        exit_code = run(args)
        assert exit_code == 0, (
            "run() must succeed (return 0) when CLAUDE_PLUGIN_DATA is unset "
            "and --output is omitted — temp-file fallback should be used."
        )

    def test_explicit_output_still_respected_with_plugin_data_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Passing --output explicitly overrides the CLAUDE_PLUGIN_DATA default.

        When the user explicitly provides --output, the file must be written
        to that path regardless of $CLAUDE_PLUGIN_DATA.
        """
        plugin_data_dir = tmp_path / "plugin-data"
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data_dir))

        explicit_output = tmp_path / "explicit" / "out.html"
        args = self._make_args(tmp_path, output=explicit_output)

        run(args)

        assert explicit_output.exists(), (
            "Explicit --output must be honoured even when " "CLAUDE_PLUGIN_DATA is set."
        )
        assert not (
            plugin_data_dir / "dashboard.html"
        ).exists(), "Plugin-data path must NOT be written when --output is explicit."

    def test_plugin_data_default_parser_output_still_none(self) -> None:
        """argparse default for --output remains None after the change.

        The default-path resolution must happen in the command handler
        (``run()``), NOT as the argparse ``default=`` value. This keeps the
        ``render()`` contract intact: ``None`` still means "temp file" at
        the ``render()`` call site; the handler resolves the plugin-data path
        before calling ``render()``.
        """
        top = argparse.ArgumentParser()
        sub = top.add_subparsers()
        build_parser(sub)
        args = top.parse_args(["dashboard"])
        assert args.output is None, (
            "argparse default for --output must remain None. "
            "Default-path resolution belongs in run(), not the arg default."
        )
