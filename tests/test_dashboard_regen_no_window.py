"""Regression test for issue #188 — dashboard-regen hook must not pass --window.

The hook previously passed ``--window 7d`` to the dashboard subcommand,
causing the aggregator to drop prior-period data needed by the Economy v1
week-over-week comparison panes.  After the fix the regen subprocess must
be invoked without any ``--window`` argument.

Strategy: we inject a fake ``claude_prospector`` module via ``PYTHONPATH``
that records its argv to a JSON file and exits 0.  Then we run the hook as
a subprocess, let it fire the regen step, and inspect the recorded argv for
the absence of ``--window``.  This exercises the full hook subprocess path
without depending on the real dashboard command.

The ``valid_setup_state`` fixture is reused here so the version-check step
passes and the hook reaches the regen step rather than short-circuiting on
a version mismatch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

_WORKTREE = Path(__file__).parent.parent
_HOOK_PATH = _WORKTREE / "hooks" / "dashboard-regen.py"

# Ensure the hook's lib/ directory is importable (same as other hook tests).
sys.path.insert(0, str(_WORKTREE / "hooks" / "lib"))
import setup_state as _setup_state  # noqa: E402

_MANIFEST_VERSION = _setup_state.get_current_version()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_env(
    tmp_path: Path,
    *,
    manifest_version: str = _MANIFEST_VERSION,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build environment dict for a hook invocation with autoregen=true.

    Sets up all required env vars so the hook reaches the regen step.

    Args:
        tmp_path: pytest per-test temporary directory.
        manifest_version: Version string to embed in the plugin manifest.
        extra: Extra vars to merge (last wins).

    Returns:
        Environment dict with all CLAUDE_PROSPECTOR_* vars set.
    """
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"autoregen": True}), encoding="utf-8")

    dashboard_file = tmp_path / "dashboard.html"
    hook_log = tmp_path / "hook.log"

    plugin_root = tmp_path / "plugin-root"
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps({"version": manifest_version}), encoding="utf-8"
    )
    claude_plugin_dir = plugin_root / ".claude-plugin"
    claude_plugin_dir.mkdir(parents=True, exist_ok=True)
    (claude_plugin_dir / "plugin.json").write_text(
        json.dumps({"version": _MANIFEST_VERSION}), encoding="utf-8"
    )

    env = {
        **os.environ,
        "CLAUDE_PROSPECTOR_CONFIG": str(cfg_path),
        "CLAUDE_PROSPECTOR_DASHBOARD": str(dashboard_file),
        "CLAUDE_PROSPECTOR_HOOK_LOG": str(hook_log),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
    }
    if extra:
        env.update(extra)
    return env


def _write_spy_module(spy_dir: Path, argv_file: Path) -> None:
    """Write a fake ``claude_prospector`` package that records its argv.

    The hook calls ``[python, "-m", "claude_prospector", "dashboard", ...]``
    for the regen step and ``[python, "-m", "claude_prospector", "--version"]``
    for the version-check step.  This fake package's ``__main__.py`` appends
    each invocation's ``sys.argv`` to *argv_file* as a JSON lines file, so we
    can inspect all calls the hook made.

    Args:
        spy_dir: Directory to create the fake package inside.
        argv_file: Path where recorded argv lists will be appended as JSONL.
    """
    pkg_dir = spy_dir / "claude_prospector"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # __init__.py — empty, just makes it a package.
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")

    # __main__.py — appends sys.argv as a JSON line, then responds to the
    # hook's version-check (--version) with the current package version so
    # the version gate passes, and exits 0 for all other invocations.
    main_code = textwrap.dedent(f"""\
        import json
        import sys
        from pathlib import Path

        argv_file = Path({str(argv_file)!r})
        # Append this invocation's argv as a JSON line.
        with argv_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sys.argv) + "\\n")

        # Satisfy the hook's --version check.
        if "--version" in sys.argv:
            import importlib.metadata
            try:
                ver = importlib.metadata.version("claude-prospector")
            except Exception:
                ver = "0.0.0"
            sys.stdout.write(f"claude-prospector {{ver}}\\n")

        sys.exit(0)
    """)
    (pkg_dir / "__main__.py").write_text(main_code, encoding="utf-8")


def _run_hook(
    env: dict[str, str],
    stdin_payload: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the dashboard-regen hook as a subprocess.

    Args:
        env: Environment dict (from _make_env).
        stdin_payload: JSON payload to write to stdin. Defaults to ``{}``.

    Returns:
        CompletedProcess with stdout, stderr, returncode.
    """
    payload = json.dumps(stdin_payload or {})
    cmd = [sys.executable, str(_HOOK_PATH)]
    return subprocess.run(
        cmd,
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKTREE),
    )


# ---------------------------------------------------------------------------
# Issue #188 regression: regen subprocess must not include --window
# ---------------------------------------------------------------------------


class TestRegenSubprocessNoWindow:
    """The dashboard-regen hook must not pass --window to the dashboard cmd.

    Regression for issue #188: the hook previously hardcoded ``--window 7d``
    in the subprocess call, causing the aggregator to drop the prior-period
    data required by Economy v1 week-over-week comparison panes.
    """

    def test_regen_command_does_not_contain_window_flag(
        self,
        tmp_path: Path,
        valid_setup_state: Path,
    ) -> None:
        """The subprocess regen call must not include '--window' in its argv.

        This is the primary regression test for issue #188.  We inject a
        spy ``claude_prospector`` package via PYTHONPATH so the hook's
        version-check and regen calls both succeed without the real package,
        and the regen argv is captured to a JSON file for inspection.
        """
        argv_file = tmp_path / "regen_argv.json"
        spy_dir = tmp_path / "spy"
        _write_spy_module(spy_dir, argv_file)

        env = _make_env(tmp_path)
        # Prepend spy_dir to PYTHONPATH so Python finds our fake package
        # ahead of the real claude_prospector.
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(spy_dir) + os.pathsep + existing_pythonpath
            if existing_pythonpath
            else str(spy_dir)
        )

        result = _run_hook(env)
        assert (
            result.returncode == 0
        ), f"Hook exited non-zero. stderr: {result.stderr!r}"
        assert argv_file.exists(), (
            f"Spy argv file was not written — hook may not have reached "
            f"the regen step. hook returncode={result.returncode}, "
            f"stderr={result.stderr!r}"
        )

        all_calls = [
            json.loads(line)
            for line in argv_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # Find the dashboard regen call (argv contains "dashboard").
        regen_calls = [a for a in all_calls if "dashboard" in a]
        assert len(regen_calls) == 1, (
            f"Expected exactly one dashboard regen call; "
            f"got {len(regen_calls)} from {all_calls!r}"
        )
        regen_argv = regen_calls[0]
        assert "--window" not in regen_argv, (
            f"The dashboard-regen hook must not pass '--window' to the "
            f"dashboard subcommand (issue #188). "
            f"Captured regen argv: {regen_argv!r}"
        )

    def test_regen_command_contains_output_and_no_open(
        self,
        tmp_path: Path,
        valid_setup_state: Path,
    ) -> None:
        """Regen command must still contain --output and --no-open after fix.

        Sanity-check that removing --window did not accidentally remove
        other required arguments from the hook's subprocess call.
        """
        argv_file = tmp_path / "regen_argv.json"
        spy_dir = tmp_path / "spy"
        _write_spy_module(spy_dir, argv_file)

        env = _make_env(tmp_path)
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(spy_dir) + os.pathsep + existing_pythonpath
            if existing_pythonpath
            else str(spy_dir)
        )

        _run_hook(env)

        assert (
            argv_file.exists()
        ), "Spy argv file not written — hook did not reach the regen step."

        all_calls = [
            json.loads(line)
            for line in argv_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        regen_calls = [a for a in all_calls if "dashboard" in a]
        assert len(regen_calls) == 1, (
            f"Expected exactly one dashboard regen call; "
            f"got {len(regen_calls)} from {all_calls!r}"
        )
        regen_argv = regen_calls[0]
        assert (
            "--output" in regen_argv
        ), f"Regen command must still contain '--output'; got: {regen_argv!r}"
        assert (
            "--no-open" in regen_argv
        ), f"Regen command must still contain '--no-open'; got: {regen_argv!r}"
