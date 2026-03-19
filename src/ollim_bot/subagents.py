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

from ollim_bot.config import BOT_NAME, USER_NAME
from ollim_bot.storage import DATA_DIR, parse_frontmatter

log = logging.getLogger(__name__)

_SOURCE_DIR = Path(__file__).parent / "subagents"
_AGENTS_DIR = DATA_DIR / ".claude" / "agents"


def _expand(text: str) -> str:
    return text.replace("{USER_NAME}", USER_NAME).replace("{BOT_NAME}", BOT_NAME)


# Bundled agents that were renamed or removed. Maps old filename → replacement
# (or None if removed entirely). Cleaned up on install so stale agents don't
# linger after auto-update. Safe to trim entries after a few release cycles.
_MIGRATIONS: dict[str, str | None] = {
    "guide.md": "ollim-bot-guide.md",
}


def install_agents() -> None:
    """Copy bundled agent specs to .claude/agents/ with template expansion.

    Skips files that already exist (user customizations persist across updates).
    """
    _AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    for old_name, new_name in _MIGRATIONS.items():
        old_path = _AGENTS_DIR / old_name
        if old_path.is_file():
            old_path.unlink()
            log.info("Migrated agent: %s → %s", old_name, new_name or "(removed)")
    for source in sorted(_SOURCE_DIR.glob("*.md")):
        target = _AGENTS_DIR / source.name
        if target.exists():
            continue
        target.write_text(_expand(source.read_text(encoding="utf-8")), encoding="utf-8")
        log.info("Installed bundled agent: %s", source.name)


def _extract_tools(path: Path) -> tuple[str, list[str]] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("Skipping unreadable agent spec %s: %s", path.name, exc)
        return None
    meta = parse_frontmatter(text)
    if not meta:
        return None
    raw_tools = meta.get("tools")
    if not raw_tools:
        return None
    name = str(meta.get("name", path.stem))
    # SDK accepts both comma-separated string and YAML list for tools
    if isinstance(raw_tools, str):
        tools = [t.strip() for t in raw_tools.split(",")]
    elif isinstance(raw_tools, list):
        tools = [str(t) for t in raw_tools]
    else:
        return None
    return name, tools


def load_agent_tool_sets() -> dict[str, list[str]]:
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
