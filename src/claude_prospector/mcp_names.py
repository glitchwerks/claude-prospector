"""Normalize MCP tool names."""

from __future__ import annotations


def normalize_mcp_tool_name(raw: str) -> str | None:
    """Normalize an MCP tool name to '<server>.<method>'.

    Handles both forms:
    - Plugin-scoped: ``mcp__plugin_<plugin>_<server>__<method>``
      e.g. ``mcp__plugin_github_github__create_issue`` → ``github.create_issue``
    - Direct: ``mcp__<server>__<method>``
      e.g. ``mcp__azure__storage`` → ``azure.storage``

    Returns None when the name is malformed (starts with ``mcp__`` but
    does not contain the expected structural separators after stripping
    the plugin segment), so the caller can fall back to the ``other``
    action class. This provides forward-compatibility when new MCP naming
    conventions appear in future Claude Code versions.

    Args:
        raw: The raw tool name from the transcript.

    Returns:
        A normalised ``<server>.<method>`` string, or None if the name
        is structurally malformed.
    """
    if not raw.startswith("mcp__"):
        return None
    remainder = raw[len("mcp__") :]

    # Strip the plugin segment if present.
    # Plugin form: plugin_<plugin>_<server>__<method>
    # After stripping "plugin_", the next segment is "<plugin>_<server>"
    # which is separated from <method> by "__".
    if remainder.startswith("plugin_"):
        after_plugin = remainder[len("plugin_") :]
        # after_plugin is "<plugin>_<server>__<method>" — split once on "_"
        # to skip the plugin label, leaving "<server>__<method>".
        parts = after_plugin.split("_", 1)
        if len(parts) < 2:
            return None  # Malformed: nothing after plugin label.
        remainder = parts[1]

    # remainder is now "<server>__<method>" for both forms.
    if "__" not in remainder:
        return None  # Malformed: no method separator.
    server, _, method = remainder.partition("__")
    if not server or not method:
        return None  # Malformed: empty server or method.
    return f"{server}.{method}"
