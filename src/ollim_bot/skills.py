"""Skill data model and directory-based persistence.

Skills are reusable instruction sets stored as directories under ~/.ollim-bot/skills/.
Each skill is a directory containing a SKILL.md with YAML frontmatter (name, description)
and a markdown body (instructions). Routines and reminders reference skills by name.

Dynamic context injection: skill messages can contain !`command` markers that are expanded
to command stdout at fire time (before the agent sees the prompt).
"""

import logging
import re
import shlex
import subprocess
import time
from dataclasses import dataclass

import yaml

from ollim_bot.storage import DATA_DIR, parse_md

SKILLS_DIR = DATA_DIR / "skills"
_SKILLS_DIR_RESOLVED = SKILLS_DIR.resolve()

log = logging.getLogger(__name__)

_COMMAND_PATTERN = re.compile(r"!`([^`]+)`")
_COMMAND_TIMEOUT = 10  # per-command timeout (seconds)
_TOTAL_TIMEOUT = 30  # total wall-clock cap across all commands in one expansion
_MAX_OUTPUT = 2000  # truncate stdout to prevent prompt bloat


@dataclass(frozen=True, slots=True)
class Skill:
    name: str  # lowercase, hyphens — must match directory name
    description: str  # what the skill does and when to use it
    message: str  # the markdown body (instructions)
    allowed_tools: list[str] | None = None  # tool dependencies (merged into host job)


def _parse_skill(text: str) -> Skill | None:
    """Parse a SKILL.md file into a Skill. Returns None for invalid files."""
    try:
        return parse_md(text, Skill)
    except (ValueError, yaml.YAMLError, TypeError, KeyError):
        return None


def list_skills() -> list[Skill]:
    """Read all skills from skills/*/SKILL.md directories."""
    if not SKILLS_DIR.is_dir():
        return []
    skills: list[Skill] = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        try:
            text = (skill_dir / "SKILL.md").read_text()
        except OSError:
            continue
        skill = _parse_skill(text)
        if skill is None:
            log.warning("Skipping corrupt skill: %s", skill_dir.name)
            continue
        skills.append(skill)
    return skills


def read_skill(name: str) -> Skill | None:
    """Read a single skill by name. Returns None if not found or corrupt."""
    skill_md = SKILLS_DIR / name / "SKILL.md"
    if not skill_md.resolve().is_relative_to(_SKILLS_DIR_RESOLVED):
        log.warning("Skill name contains path traversal: %s", name)
        return None
    try:
        text = skill_md.read_text()
    except OSError:
        return None
    skill = _parse_skill(text)
    if skill is None:
        log.warning("Corrupt skill: %s", name)
    return skill


def _run_command(cmd: str, remaining: float) -> str:
    """Run a single command and return its output or an error marker."""
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return f"[command parse error: {cmd}]"
    timeout = min(_COMMAND_TIMEOUT, remaining)
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(SKILLS_DIR.parent),
        )
    except subprocess.TimeoutExpired:
        return f"[command timed out: {cmd}]"
    except FileNotFoundError:
        return f"[command not found: {cmd}]"
    if result.returncode != 0:
        stderr = result.stderr.strip()
        first_line = stderr.split("\n", maxsplit=1)[0] if stderr else ""
        suffix = f": {first_line}" if first_line else ""
        return f"[command failed (exit {result.returncode}): {cmd}{suffix}]"
    output = result.stdout.rstrip("\n")
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "\n[...truncated]"
    return output


def _expand_commands(text: str) -> str:
    """Expand !`command` markers in skill text to command stdout.

    Runs commands sequentially with a total wall-clock cap. Blocks the caller
    for the duration of command execution (sync subprocess).
    """
    commands = _COMMAND_PATTERN.findall(text)
    if not commands:
        return text
    results: dict[str, str] = {}
    start = time.monotonic()
    for cmd in commands:
        if cmd in results:
            continue
        elapsed = time.monotonic() - start
        remaining = _TOTAL_TIMEOUT - elapsed
        if remaining <= 0:
            results[cmd] = f"[command skipped (total timeout): {cmd}]"
            continue
        results[cmd] = _run_command(cmd, remaining)
    return _COMMAND_PATTERN.sub(lambda m: results[m.group(1)], text)


def load_skills(skill_names: list[str] | None) -> list[Skill]:
    """Load referenced skills by name. Shared entry point to avoid double reads."""
    if not skill_names:
        return []
    loaded = []
    for name in skill_names:
        skill = read_skill(name)
        if skill is not None:
            loaded.append(skill)
    return loaded


def build_skills_section(skills: list[Skill]) -> str:
    """Expand commands and format as a SKILL INSTRUCTIONS block."""
    if not skills:
        return ""
    lines = ["SKILL INSTRUCTIONS:\n"]
    for skill in skills:
        expanded = _expand_commands(skill.message)
        lines.append(f"### {skill.name}\n{expanded}\n")
    return "\n".join(lines) + "\n"


def collect_skill_tools(skills: list[Skill]) -> list[str]:
    """Collect tool dependencies from referenced skills. Deduplicated."""
    tools: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        if skill.allowed_tools:
            for tool in skill.allowed_tools:
                if tool not in seen:
                    seen.add(tool)
                    tools.append(tool)
    return tools
