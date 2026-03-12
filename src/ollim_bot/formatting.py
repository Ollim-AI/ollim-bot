"""Tool-label formatting helpers shared by agent and permissions."""

import json

# Tool name → input key(s) to extract for informative labels.
TOOL_LABEL_KEYS: dict[str, str | tuple[str, ...]] = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Bash": "command",
    "Grep": ("pattern", "path"),
    "Glob": "pattern",
    "WebSearch": "query",
    "WebFetch": "url",
}


def _shorten_path(path: str) -> str:
    """Reduce a path to its last two components."""
    parts = path.rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 2 else path


def escape_md(s: str) -> str:
    """Escape characters that break Discord italic markdown."""
    return s.replace("*", "\\*").replace("_", "\\_")


def strip_mcp_namespace(name: str) -> str:
    """Strip MCP namespace prefix: ``mcp__server__tool`` → ``tool``."""
    parts = name.split("__", 2)
    if len(parts) == 3 and parts[0] == "mcp":
        return parts[2]
    return name


def format_tool_label(name: str, input_json: str) -> str:
    """Build a descriptive tool-use label like ``Write(reminders/foo.md)``."""
    cleaned = strip_mcp_namespace(name)
    if cleaned != name:
        return cleaned

    try:
        inp = json.loads(input_json) if input_json else {}
    except json.JSONDecodeError:
        return name

    # Agent tool: use agent name as prefix, description as parameter.
    if name == "Agent":
        return format_task_label(inp.get("name") or inp.get("subagent_type", ""), inp.get("description", ""))

    keys = TOOL_LABEL_KEYS.get(name)
    if keys is None:
        return name
    if isinstance(keys, str):
        keys = (keys,)

    parts: list[str] = []
    for key in keys:
        val = inp.get(key, "")
        if not val:
            continue
        if key == "file_path":
            val = _shorten_path(val)
        elif key == "command":
            val = val.split("\n")[0][:50]
        parts.append(escape_md(str(val)))

    return f"{name}({', '.join(parts)})" if parts else name


def format_task_label(agent_name: str, description: str) -> str:
    """Build an Agent label like ``guide(search for docs)``."""
    prefix = escape_md(agent_name) if agent_name else "Agent"
    if not description:
        return prefix
    return f"{prefix}({escape_md(description)})"
