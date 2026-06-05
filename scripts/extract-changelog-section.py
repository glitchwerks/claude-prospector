#!/usr/bin/env python3
"""Extract a single version's section from a Keep-a-Changelog formatted file.

Usage::

    python scripts/extract-changelog-section.py <version> [<changelog-path>]

Arguments:
    version: The version to extract, e.g. ``0.10.0`` or ``v0.10.0`` (the
        leading ``v`` is stripped automatically).
    changelog-path: Path to the CHANGELOG file. Defaults to ``CHANGELOG.md``
        relative to the current working directory.

Exit codes:
    0: Section found; content written to stdout.
    1: Version not found in the file, or the CHANGELOG file does not exist.

The output is the content of the ``## [X.Y.Z]`` section — everything after the
heading line up to (but not including) the next ``## `` heading — with leading
and trailing blank lines stripped.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def extract_section(changelog_text: str, version: str) -> str | None:
    """Return the body of the ``## [version]`` section, or ``None`` if absent.

    The section starts on the line immediately after the matching
    ``## [X.Y.Z]`` heading and ends just before the next ``## `` heading
    (or at the end of the file, whichever comes first).  Leading and
    trailing blank lines are stripped from the result.

    Args:
        changelog_text: Full text of the CHANGELOG file.
        version: Version to look for (without a leading ``v``).

    Returns:
        The section body as a stripped string, or ``None`` when the version
        is not present in the file.
    """
    # Match lines like "## [0.10.0] - 2026-05-30" (date is optional).
    heading_re = re.compile(r"^## \[", re.MULTILINE)
    target_re = re.compile(
        r"^## \[" + re.escape(version) + r"\]",
        re.MULTILINE,
    )

    match = target_re.search(changelog_text)
    if match is None:
        return None

    # Find the start of the section body (the line after the heading).
    section_start = changelog_text.index("\n", match.start()) + 1

    # Find the next ## heading after the current one.
    next_heading = heading_re.search(changelog_text, section_start)
    if next_heading:
        section_body = changelog_text[section_start : next_heading.start()]
    else:
        section_body = changelog_text[section_start:]

    # Strip link-reference definitions that appear at the bottom of some sections.
    # Lines like "[0.10.0]: https://..."  are not release notes.
    lines = section_body.splitlines()
    content_lines = [
        line for line in lines if not re.match(r"^\[[\d.]+\]:\s+https?://", line)
    ]

    return "\n".join(content_lines).strip()


def main(argv: list[str] | None = None) -> int:
    """Entry point for the changelog extractor.

    Args:
        argv: Command-line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    args = argv if argv is not None else sys.argv[1:]

    if len(args) < 1:
        print(
            "Usage: extract-changelog-section.py <version> [<changelog-path>]",
            file=sys.stderr,
        )
        return 1

    raw_version = args[0]
    # Strip a leading 'v' so both "0.10.0" and "v0.10.0" are accepted.
    version = raw_version.lstrip("v")

    changelog_path = Path(args[1]) if len(args) >= 2 else Path("CHANGELOG.md")

    if not changelog_path.exists():
        print(
            f"error: CHANGELOG file not found: {changelog_path}",
            file=sys.stderr,
        )
        return 1

    changelog_text = changelog_path.read_text(encoding="utf-8")
    section = extract_section(changelog_text, version)

    if section is None:
        print(
            f"error: version {version!r} not found in {changelog_path}",
            file=sys.stderr,
        )
        return 1

    print(section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
