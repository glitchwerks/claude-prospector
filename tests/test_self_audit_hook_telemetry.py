"""Integration test: session-audit-prompt.py emits telemetry.

Invokes the hook script with a synthetic ``stop_hook_active=True`` payload
and a tmp ``CLAUDE_PLUGIN_DATA`` directory, then asserts that the
telemetry JSONL file was written with the expected ``state`` field.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK_SCRIPT = Path(__file__).parent.parent / "hooks" / "session-audit-prompt.py"


class TestSessionAuditHookTelemetry:
    """session-audit-prompt.py writes telemetry on each exit branch."""

    def test_stop_hook_active_writes_telemetry(self, tmp_path: Path) -> None:
        """stop_hook_active=True branch writes one telemetry entry."""
        payload = json.dumps({"stop_hook_active": True})

        result = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
            env={
                **__import__("os").environ,
                "CLAUDE_PLUGIN_DATA": str(tmp_path),
            },
        )

        assert result.returncode == 0, (
            f"Hook exited non-zero: {result.returncode}\n" f"stderr: {result.stderr}"
        )

        log_file = tmp_path / "session-audit.jsonl"
        assert (
            log_file.exists()
        ), "Telemetry file not created — did the hook call log_outcome()?"

        lines = [
            line
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 1, f"Expected 1 telemetry entry, got {len(lines)}"

        entry = json.loads(lines[0])
        assert (
            entry["state"] == "stop_hook_active"
        ), f"Expected state='stop_hook_active', got {entry['state']!r}"
