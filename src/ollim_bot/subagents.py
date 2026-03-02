"""Bundled subagent installation and tool-set extraction.

Bundled agent specs live in src/ollim_bot/subagents/*.md (YAML frontmatter +
markdown prompt). At bot init, install_agents() copies them to the SDK-expected
.claude/agents/ directory with template expansion. The SDK then loads them via
setting_sources=["project"].

load_agent_tool_sets() reads YAML frontmatter from installed agents to extract
tool declarations for tool policy validation (the SDK doesn't expose loaded
agent definitions to Python).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ollim_bot.config import BOT_NAME, USER_NAME
from ollim_bot.storage import DATA_DIR

log = logging.getLogger(__name__)

_SOURCE_DIR = Path(__file__).parent / "subagents"
_AGENTS_DIR = DATA_DIR / ".claude" / "agents"


def _expand(text: str) -> str:
    """Expand {USER_NAME} and {BOT_NAME} template variables."""
    return text.replace("{USER_NAME}", USER_NAME).replace("{BOT_NAME}", BOT_NAME)


def install_agents() -> None:
    """Copy bundled agent specs to .claude/agents/ with template expansion.

    Skips files that already exist (user customizations persist across updates).
    """
    _AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    for source in sorted(_SOURCE_DIR.glob("*.md")):
        target = _AGENTS_DIR / source.name
        try:
            with open(target, "x") as f:
                f.write(_expand(source.read_text()))
        except FileExistsError:
            continue
        log.info("Installed bundled agent: %s", source.name)


def _extract_tools(path: Path) -> tuple[str, list[str]] | None:
    """Extract (name, tools) from a single agent spec's YAML frontmatter."""
    try:
        text = path.read_text()
    except OSError as exc:
        log.warning("Skipping unreadable agent spec %s: %s", path.name, exc)
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        log.warning("Skipping corrupt agent spec %s: %s", path.name, exc)
        return None
    if not isinstance(meta, dict):
        return None
    tools = meta.get("tools")
    if not tools:
        return None
    name = str(meta.get("name", path.stem))
    # SDK accepts both comma-separated string and YAML list for tools
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]
    return name, tools


def load_agent_tool_sets() -> dict[str, list[str]]:
    """Read tool declarations from installed agent specs for policy validation."""
    tool_sets: dict[str, list[str]] = {}
    if not _AGENTS_DIR.is_dir():
        return tool_sets
    for path in sorted(_AGENTS_DIR.glob("*.md")):
        result = _extract_tools(path)
        if result is None:
            continue
        name, tools = result
        tool_sets[f"subagent:{name}"] = tools
    return tool_sets
