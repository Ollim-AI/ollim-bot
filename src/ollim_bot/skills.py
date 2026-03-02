"""Skill data model and directory-based persistence.

Skills are reusable instruction sets stored as directories under ~/.ollim-bot/skills/.
Each skill is a directory containing a SKILL.md with YAML frontmatter (name, description)
and a markdown body (instructions). Routines and reminders reference skills by name.
"""

import logging
from dataclasses import dataclass

import yaml

from ollim_bot.storage import DATA_DIR, parse_md

SKILLS_DIR = DATA_DIR / "skills"

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Skill:
    name: str  # lowercase, hyphens — must match directory name
    description: str  # what the skill does and when to use it
    message: str  # the markdown body (instructions)


def _parse_skill(text: str) -> Skill | None:
    """Parse a SKILL.md file into a Skill. Returns None for invalid files."""
    try:
        return parse_md(text, Skill)
    except (ValueError, yaml.YAMLError, TypeError):
        return None


def list_skills() -> list[Skill]:
    """Read all skills from skills/*/SKILL.md directories."""
    if not SKILLS_DIR.is_dir():
        return []
    skills: list[Skill] = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        skill = _parse_skill(skill_md.read_text())
        if skill is None:
            log.warning("Skipping corrupt skill: %s", skill_dir.name)
            continue
        skills.append(skill)
    return skills


def read_skill(name: str) -> Skill | None:
    """Read a single skill by name. Returns None if not found or corrupt."""
    skill_md = SKILLS_DIR / name / "SKILL.md"
    if not skill_md.resolve().is_relative_to(SKILLS_DIR.resolve()):
        log.warning("Skill name contains path traversal: %s", name)
        return None
    if not skill_md.exists():
        return None
    skill = _parse_skill(skill_md.read_text())
    if skill is None:
        log.warning("Corrupt skill: %s", name)
    return skill


def build_skills_section(skill_names: list[str] | None) -> str:
    """Load referenced skills and format as a SKILL INSTRUCTIONS block."""
    if not skill_names:
        return ""
    loaded = []
    for name in skill_names:
        skill = read_skill(name)
        if skill is not None:
            loaded.append(skill)
    if not loaded:
        return ""
    lines = ["SKILL INSTRUCTIONS:\n"]
    for skill in loaded:
        lines.append(f"### {skill.name}\n{skill.message}\n")
    return "\n".join(lines) + "\n"


def build_skill_index() -> str:
    """Build the dynamic skill index for the system prompt.

    Returns an empty string when no skills exist.
    """
    skills = list_skills()
    if not skills:
        return ""
    lines = ["Available skills:"]
    for skill in skills:
        lines.append(f"- **{skill.name}**: {skill.description}")
    return "\n".join(lines)
