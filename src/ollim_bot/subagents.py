"""File-based subagent spec loading.

Subagent specs are YAML frontmatter + markdown prompt files.
Source defaults live in src/ollim_bot/subagents/*.md.
Runtime overrides in ~/.ollim-bot/subagents/*.md replace the entire spec.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from claude_agent_sdk import AgentDefinition

from ollim_bot.config import BOT_NAME, USER_NAME
from ollim_bot.storage import DATA_DIR, parse_md

log = logging.getLogger(__name__)

_SOURCE_DIR = Path(__file__).parent / "subagents"
_OVERRIDE_DIR = DATA_DIR / "subagents"


class _SafeMap(dict[str, str]):
    """Dict that leaves unknown {placeholders} verbatim instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


_TEMPLATE_VARS = _SafeMap({"USER_NAME": USER_NAME, "BOT_NAME": BOT_NAME})

_ModelName = Literal["sonnet", "opus", "haiku", "inherit"]


@dataclass(frozen=True, slots=True)
class SubagentSpec:
    name: str
    description: str
    message: str  # prompt body
    model: _ModelName | None = None
    tools: list[str] | None = None


def _load_spec(path: Path) -> SubagentSpec | None:
    """Parse a single spec file. Returns None on error."""
    try:
        return parse_md(path.read_text(), SubagentSpec)
    except (ValueError, OSError, TypeError, yaml.YAMLError) as exc:
        log.warning("Skipping corrupt subagent spec %s: %s", path.name, exc)
        return None


def load_subagent_specs() -> dict[str, SubagentSpec]:
    """Load specs: source defaults, then override from DATA_DIR/subagents/."""
    specs: dict[str, SubagentSpec] = {}

    # Source defaults
    if _SOURCE_DIR.is_dir():
        for path in sorted(_SOURCE_DIR.glob("*.md")):
            spec = _load_spec(path)
            if spec is not None:
                specs[spec.name] = spec

    # Runtime overrides (full replacement)
    if _OVERRIDE_DIR.is_dir():
        for path in sorted(_OVERRIDE_DIR.glob("*.md")):
            spec = _load_spec(path)
            if spec is not None:
                if spec.name in specs:
                    log.info("Subagent %r overridden by %s", spec.name, path)
                specs[spec.name] = spec

    return specs


def build_agent_definitions(
    specs: dict[str, SubagentSpec],
) -> dict[str, AgentDefinition]:
    """Convert SubagentSpecs into SDK AgentDefinition objects."""
    definitions: dict[str, AgentDefinition] = {}
    for name, spec in specs.items():
        prompt = spec.message.format_map(_TEMPLATE_VARS)
        definitions[name] = AgentDefinition(
            description=spec.description.format_map(_TEMPLATE_VARS),
            prompt=prompt,
            tools=spec.tools or [],
            model=spec.model,
        )
    return definitions
