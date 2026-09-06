"""Classify Claude Code slash commands using a packaged catalog."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from importlib import resources
from typing import Literal


CommandKind = Literal["builtin", "bundled_skill", "workflow", "unclassified"]
_COMMAND_NAME_RE = re.compile(r"/[^\s<>]+")


@dataclass(frozen=True, slots=True)
class CommandCatalog:
    """An auditable snapshot of Claude Code command categories.

    Attributes:
        available: Whether the packaged catalog loaded successfully.
        source_url: Official documentation URL used to build the snapshot.
        retrieved_at: ISO date when the source was retrieved.
        builtins: Literal names classified as built-in commands.
        bundled_skills: Literal names classified as bundled skills.
        workflows: Literal names classified as bundled workflows.
    """

    available: bool = False
    source_url: str | None = None
    retrieved_at: str | None = None
    builtins: frozenset[str] = frozenset()
    bundled_skills: frozenset[str] = frozenset()
    workflows: frozenset[str] = frozenset()

    def classify(self, command_name: str) -> CommandKind:
        """Classify one literal slash-command name.

        Args:
            command_name: Command name including its leading slash.

        Returns:
            The catalog category, or ``"unclassified"`` when unknown.
        """
        if command_name in self.builtins:
            return "builtin"
        if command_name in self.bundled_skills:
            return "bundled_skill"
        if command_name in self.workflows:
            return "workflow"
        return "unclassified"


def _validated_commands(payload: object, field_name: str) -> frozenset[str]:
    """Validate and normalize one catalog category.

    Args:
        payload: Decoded JSON value for the category.
        field_name: Category name used in validation errors.

    Returns:
        Validated unique command names.

    Raises:
        TypeError: If the value is not a list of strings.
        ValueError: If names are duplicated or malformed.
    """
    if not isinstance(payload, list) or not all(
        isinstance(name, str) for name in payload
    ):
        raise TypeError(f"{field_name} must be a list of strings")
    names = frozenset(payload)
    if len(names) != len(payload):
        raise ValueError(f"{field_name} contains duplicate names")
    if any(_COMMAND_NAME_RE.fullmatch(name) is None for name in names):
        raise ValueError(f"{field_name} contains an invalid command name")
    return names


def _catalog_from_payload(payload: object) -> CommandCatalog:
    """Build a catalog only when its decoded JSON schema is valid.

    Args:
        payload: Decoded catalog JSON.

    Returns:
        An available, semantically validated command catalog.

    Raises:
        KeyError: If a required field is absent.
        TypeError: If a field has the wrong type.
        ValueError: If provenance or command categories are invalid.
    """
    if not isinstance(payload, dict):
        raise TypeError("catalog must be an object")
    source_url = payload["source_url"]
    retrieved_at = payload["retrieved_at"]
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise ValueError("source_url must be an HTTPS URL")
    if not isinstance(retrieved_at, str):
        raise TypeError("retrieved_at must be a string")
    date.fromisoformat(retrieved_at)

    builtins = _validated_commands(payload["builtins"], "builtins")
    bundled_skills = _validated_commands(
        payload["bundled_skills"],
        "bundled_skills",
    )
    workflows = _validated_commands(payload["workflows"], "workflows")
    if builtins & bundled_skills or builtins & workflows or bundled_skills & workflows:
        raise ValueError("command categories must be disjoint")

    return CommandCatalog(
        available=True,
        source_url=source_url,
        retrieved_at=retrieved_at,
        builtins=builtins,
        bundled_skills=bundled_skills,
        workflows=workflows,
    )


@lru_cache(maxsize=1)
def load_command_catalog() -> CommandCatalog:
    """Load the packaged command catalog.

    Returns:
        The packaged catalog, or an unavailable catalog when its resource is
        missing or malformed.
    """
    try:
        catalog_text = (
            resources.files("claude_prospector")
            .joinpath("data/claude-code-commands.json")
            .read_text(encoding="utf-8")
        )
        payload = json.loads(catalog_text)
        return _catalog_from_payload(payload)
    except (KeyError, OSError, TypeError, ValueError):
        return CommandCatalog()
