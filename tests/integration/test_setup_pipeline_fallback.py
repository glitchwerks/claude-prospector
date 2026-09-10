"""Tests for the approval-gated setup source-install fallback."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from integration import setup_pipeline  # noqa: E402


def test_pypi_failure_uses_approved_sha_pinned_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed default install falls back only after explicit approval."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    pip_commands: list[list[str]] = []
    approval_prompts: list[str] = []
    commit_sha = "1a2b3c4d5e6f789012345678901234567890abcd"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        pip_commands.append(args)
        if len(pip_commands) == 1:
            return subprocess.CompletedProcess(
                args,
                1,
                "Looking in indexes: https://corp.example/simple",
                "No matching distribution found for claude-prospector==0.14.0",
            )
        return subprocess.CompletedProcess(args, 0, "installed from source", "")

    def approve(prompt: str) -> bool:
        approval_prompts.append(prompt)
        return True

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    setup_pipeline.pip_install(
        venv_dir,
        "0.14.0",
        approve_fallback=approve,
        tag_resolver=lambda version: commit_sha,
    )

    assert approval_prompts == [
        "pip install 'claude-prospector==0.14.0' failed (exit 1):\n"
        "stdout: Looking in indexes: https://corp.example/simple\n"
        "stderr: No matching distribution found for "
        "claude-prospector==0.14.0"
    ]
    assert pip_commands[1][-1] == (
        "git+https://github.com/glitchwerks/claude-prospector.git@" f"{commit_sha}"
    )
    assert venv_dir.exists()


def test_pypi_failure_without_approval_callback_cleans_partial_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Default-source failure requires explicit approval before fallback."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(
            args,
            1,
            "corporate index selected",
            "required version unavailable",
        )

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(venv_dir, "0.14.0")

    message = str(exc_info.value)
    assert "requires explicit user approval" in message
    assert "corporate index selected" in message
    assert "required version unavailable" in message
    assert not venv_dir.exists()


def test_declined_fallback_reports_pypi_failure_and_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Declining GitHub access keeps the PyPI diagnostics and fails setup."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(
            args,
            1,
            "using proxy index",
            "package version missing",
        )

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=lambda prompt: False,
        )

    message = str(exc_info.value)
    assert "GitHub fallback was declined" in message
    assert "using proxy index" in message
    assert "package version missing" in message
    assert not venv_dir.exists()


def test_resolve_release_tag_prefers_peeled_annotated_commit() -> None:
    """An annotated version tag resolves to its immutable peeled commit."""
    tag_object_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    commit_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    commands: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            (
                f"{tag_object_sha}\trefs/tags/v0.14.0\n"
                f"{commit_sha}\trefs/tags/v0.14.0^{{}}\n"
            ),
            "",
        )

    resolved = setup_pipeline.resolve_release_tag("0.14.0", run=fake_run)

    assert resolved == commit_sha
    assert commands == [
        [
            "git",
            "ls-remote",
            "https://github.com/glitchwerks/claude-prospector.git",
            "refs/tags/v0.14.0",
            "refs/tags/v0.14.0^{}",
        ]
    ]


def test_fallback_rejects_non_sha_resolution_and_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fallback never installs from a mutable or malformed Git ref."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        if "claude-prospector==0.14.0" in args:
            return subprocess.CompletedProcess(args, 1, "", "version unavailable")
        return subprocess.CompletedProcess(args, 0, "should not install", "")

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=lambda prompt: True,
            tag_resolver=lambda version: "v0.14.0",
        )

    assert "valid 40-character commit SHA" in str(exc_info.value)
    assert not venv_dir.exists()


def test_resolve_release_tag_rejects_malformed_remote_sha() -> None:
    """Tag resolution rejects output that is not an immutable commit SHA."""

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            "main\trefs/tags/v0.14.0\n",
            "",
        )

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.resolve_release_tag("0.14.0", run=fake_run)

    assert "valid 40-character commit SHA" in str(exc_info.value)


def test_resolve_release_tag_reports_timeout_actionably() -> None:
    """A stalled GitHub lookup reports a network-oriented setup error."""

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, 30)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.resolve_release_tag("0.14.0", run=fake_run)

    assert "timed out" in str(exc_info.value)
    assert "GitHub network access" in str(exc_info.value)


def test_resolve_release_tag_reports_missing_git_actionably() -> None:
    """A missing Git executable explains the prerequisite."""

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.resolve_release_tag("0.14.0", run=fake_run)

    assert "Git is required" in str(exc_info.value)


@pytest.mark.parametrize("ref_suffix", ["", "^{}"])
def test_resolve_release_tag_rejects_duplicate_applicable_refs(
    ref_suffix: str,
) -> None:
    """Ambiguous duplicate tag lines fail closed instead of being collapsed."""
    first_sha = "1111111111111111111111111111111111111111"
    second_sha = "2222222222222222222222222222222222222222"
    tag_ref = f"refs/tags/v0.14.0{ref_suffix}"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            f"{first_sha}\t{tag_ref}\n{second_sha}\t{tag_ref}\n",
            "",
        )

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.resolve_release_tag("0.14.0", run=fake_run)

    assert "duplicate" in str(exc_info.value).lower()


def test_peeled_ref_ignores_duplicate_direct_tag_objects() -> None:
    """Annotated-tag resolution considers only the peeled ref applicable."""
    commit_sha = "7777777777777777777777777777777777777777"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            (
                "1111111111111111111111111111111111111111"
                "\trefs/tags/v0.14.0\n"
                "2222222222222222222222222222222222222222"
                "\trefs/tags/v0.14.0\n"
                f"{commit_sha}\trefs/tags/v0.14.0^{{}}\n"
            ),
            "",
        )

    assert setup_pipeline.resolve_release_tag("0.14.0", run=fake_run) == commit_sha


def test_fallback_pip_timeout_preserves_diagnostics_and_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stalled source install fails actionably and removes the partial venv."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    pip_attempts = 0
    commit_sha = "3333333333333333333333333333333333333333"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal pip_attempts
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        pip_attempts += 1
        if pip_attempts == 1:
            return subprocess.CompletedProcess(
                args,
                1,
                "corporate index",
                "version unavailable",
            )
        raise subprocess.TimeoutExpired(args, 180)

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=lambda prompt: True,
            tag_resolver=lambda version: commit_sha,
        )

    message = str(exc_info.value)
    assert "corporate index" in message
    assert "version unavailable" in message
    assert "GitHub source install timed out" in message
    assert not venv_dir.exists()


def test_fallback_pip_failure_preserves_both_attempts_and_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A source build failure retains diagnostics from both install attempts."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    pip_attempts = 0
    commit_sha = "4444444444444444444444444444444444444444"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal pip_attempts
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        pip_attempts += 1
        if pip_attempts == 1:
            return subprocess.CompletedProcess(
                args,
                1,
                "corporate index",
                "version unavailable",
            )
        return subprocess.CompletedProcess(
            args,
            1,
            "building wheel",
            "build dependency unavailable",
        )

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=lambda prompt: True,
            tag_resolver=lambda version: commit_sha,
        )

    message = str(exc_info.value)
    assert "corporate index" in message
    assert "version unavailable" in message
    assert "building wheel" in message
    assert "build dependency unavailable" in message
    assert not venv_dir.exists()


def test_override_failure_never_offers_github_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The explicit pip-spec override remains authoritative on failure."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    approvals = 0

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 1, "", "override failed")

    def approve(prompt: str) -> bool:
        nonlocal approvals
        approvals += 1
        return True

    monkeypatch.setenv("CLAUDE_PROSPECTOR_PIP_SPEC", "./corporate-wheel.whl")
    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=approve,
        )

    assert "./corporate-wheel.whl" in str(exc_info.value)
    assert approvals == 0
    assert not venv_dir.exists()


def test_empty_override_remains_authoritative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicitly empty pip override is attempted without fallback."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    pip_commands: list[list[str]] = []
    approvals = 0

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        pip_commands.append(args)
        return subprocess.CompletedProcess(args, 1, "", "no requirement specified")

    def approve(prompt: str) -> bool:
        nonlocal approvals
        approvals += 1
        return True

    monkeypatch.setenv("CLAUDE_PROSPECTOR_PIP_SPEC", "")
    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=approve,
        )

    assert pip_commands == [
        [str(setup_pipeline.get_venv_python(venv_dir)), "-m", "pip", "install"]
    ]
    assert "pip install '' failed" in str(exc_info.value)
    assert approvals == 0
    assert not venv_dir.exists()


def test_resolve_release_tag_accepts_lightweight_tag() -> None:
    """A lightweight version tag resolves from its direct immutable ref."""
    commit_sha = "5555555555555555555555555555555555555555"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            f"{commit_sha}\trefs/tags/v0.14.0\n",
            "",
        )

    assert setup_pipeline.resolve_release_tag("0.14.0", run=fake_run) == commit_sha


@pytest.mark.parametrize(
    "git_error",
    [
        FileNotFoundError("git"),
        PermissionError("git execution denied"),
        subprocess.TimeoutExpired("git", 30),
    ],
)
def test_git_resolution_failure_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git_error: Exception,
) -> None:
    """Git lookup launch failures remove the partial environment."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["git", "ls-remote"]:
            raise git_error
        return subprocess.CompletedProcess(args, 1, "", "version unavailable")

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=lambda prompt: True,
        )

    assert "GitHub fallback failed" in str(exc_info.value)
    assert "version unavailable" in str(exc_info.value)
    assert not venv_dir.exists()


def test_nonzero_git_lookup_preserves_pypi_diagnostics_and_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed remote lookup retains both diagnostics and removes the venv."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(
                args,
                128,
                "remote lookup started",
                "corporate proxy denied GitHub",
            )
        return subprocess.CompletedProcess(
            args,
            1,
            "corporate package index",
            "required package version unavailable",
        )

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=lambda prompt: True,
        )

    message = str(exc_info.value)
    assert "corporate package index" in message
    assert "required package version unavailable" in message
    assert "git ls-remote failed (exit 128)" in message
    assert "corporate proxy denied GitHub" in message
    assert not venv_dir.exists()


def test_missing_remote_tag_preserves_pypi_diagnostics_and_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A successful lookup without the version tag fails setup cleanly."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(
                args,
                0,
                "9999999999999999999999999999999999999999" "\trefs/tags/v0.13.0\n",
                "",
            )
        return subprocess.CompletedProcess(
            args,
            1,
            "corporate package index",
            "required package version unavailable",
        )

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=lambda prompt: True,
        )

    message = str(exc_info.value)
    assert "corporate package index" in message
    assert "required package version unavailable" in message
    assert "Release tag v0.14.0 was not found" in message
    assert not venv_dir.exists()


def test_pypi_timeout_can_use_approved_source_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A timed-out default index attempt may fall back after approval."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    pip_attempts = 0
    prompts: list[str] = []
    commit_sha = "6666666666666666666666666666666666666666"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal pip_attempts
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        pip_attempts += 1
        if pip_attempts == 1:
            raise subprocess.TimeoutExpired(args, 180)
        return subprocess.CompletedProcess(args, 0, "installed", "")

    def approve(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    setup_pipeline.pip_install(
        venv_dir,
        "0.14.0",
        approve_fallback=approve,
        tag_resolver=lambda version: commit_sha,
    )

    assert len(prompts) == 1
    assert "PyPI install timed out" in prompts[0]
    assert pip_attempts == 2
    assert venv_dir.exists()


def test_initial_pip_launch_failure_is_normalized_and_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A pip process launch error becomes an actionable setup failure."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    approvals = 0

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        raise PermissionError("pip execution blocked by endpoint policy")

    def approve(prompt: str) -> bool:
        nonlocal approvals
        approvals += 1
        return True

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=approve,
        )

    message = str(exc_info.value)
    assert "pip install could not start" in message
    assert "endpoint policy" in message
    assert approvals == 0
    assert not venv_dir.exists()


def test_fallback_pip_launch_failure_cleans_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A source-install launch error preserves context and cleans the venv."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    pip_attempts = 0
    commit_sha = "8888888888888888888888888888888888888888"

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal pip_attempts
        if "ensurepip" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        pip_attempts += 1
        if pip_attempts == 1:
            return subprocess.CompletedProcess(
                args,
                1,
                "corporate index",
                "version unavailable",
            )
        raise FileNotFoundError("venv python")

    monkeypatch.setattr(setup_pipeline.subprocess, "run", fake_run)

    with pytest.raises(setup_pipeline.SetupError) as exc_info:
        setup_pipeline.pip_install(
            venv_dir,
            "0.14.0",
            approve_fallback=lambda prompt: True,
            tag_resolver=lambda version: commit_sha,
        )

    message = str(exc_info.value)
    assert "version unavailable" in message
    assert "GitHub source install could not start" in message
    assert not venv_dir.exists()
