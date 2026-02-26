"""Shared JSONL I/O, markdown I/O, and git helpers for persistent data files."""

import dataclasses
import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import TypeVar

import yaml

from ollim_bot.config import TZ as TZ

DATA_DIR = Path.home() / ".ollim-bot"
STATE_DIR = DATA_DIR / "state"

T = TypeVar("T")
log = logging.getLogger(__name__)


def _find_repo(filepath: Path) -> Path | None:
    """Walk up from filepath to find the nearest git repo root."""
    for parent in filepath.parents:
        if (parent / ".git").is_dir():
            return parent
    return None


def git_commit(filepath: Path, message: str) -> None:
    """No-op when no git repo is found above filepath."""
    repo = _find_repo(filepath)
    if repo is None:
        return
    rel = filepath.relative_to(repo)
    subprocess.run(
        ["git", "add", str(rel)],
        cwd=repo,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--", str(rel)],
        cwd=repo,
        capture_output=True,
    )


def git_rm_commit(filepath: Path, message: str) -> None:
    """Remove a file from git and commit. No-op when no git repo is found."""
    repo = _find_repo(filepath)
    if repo is None:
        return
    rel = filepath.relative_to(repo)
    subprocess.run(
        ["git", "rm", "-f", str(rel)],
        cwd=repo,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--", str(rel)],
        cwd=repo,
        capture_output=True,
    )


# --- Markdown I/O ---


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug


def _serialize_md(item: T) -> str:
    """Build YAML frontmatter + markdown body from a dataclass with a `message` field."""
    data = asdict(item)  # type: ignore[call-overload]
    message = data.pop("message")
    fields = dataclasses.fields(item)  # type: ignore[arg-type]
    defaults = {f.name: f.default for f in fields if f.default is not dataclasses.MISSING and f.name != "message"}
    defaults.update(
        {
            f.name: f.default_factory()
            for f in fields
            if f.default_factory is not dataclasses.MISSING and f.name != "message"
        }
    )

    lines = ["---"]
    for key, value in data.items():
        if key in defaults and value == defaults[key]:
            continue
        if isinstance(value, str):
            lines.append(f'{key}: "{value}"')
        elif isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f'  - "{item}"' if isinstance(item, str) else f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append(message)
    return "\n".join(lines) + "\n"


def _parse_md(text: str, cls: type[T]) -> T:
    """Parse a single markdown file with YAML frontmatter into a dataclass."""
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Missing YAML frontmatter delimiters")
    yaml_text = parts[1]
    body = parts[2].strip()

    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise ValueError("YAML frontmatter is not a mapping")

    fields = {f.name: f for f in dataclasses.fields(cls)}
    filtered: dict[str, object] = {}
    for key, value in data.items():
        if key not in fields:
            continue
        expected = fields[key].type
        if expected == "str" or expected == "str | None":
            filtered[key] = str(value) if value is not None else None
        else:
            filtered[key] = value
    filtered["message"] = body
    return cls(**filtered)


def read_md_dir(dir_path: Path, cls: type[T]) -> list[T]:
    """Read all .md files in a directory into dataclass instances."""
    if not dir_path.is_dir():
        return []
    result: list[T] = []
    for filepath in sorted(dir_path.glob("*.md")):
        try:
            text = filepath.read_text()
            result.append(_parse_md(text, cls))
        except (ValueError, yaml.YAMLError, TypeError, KeyError):
            log.warning("Skipping corrupt file: %s", filepath)
    return result


def write_md(dir_path: Path, item: T, commit_msg: str) -> None:
    """Write a single item as a .md file with a slug-based filename. Atomic write."""
    dir_path.mkdir(parents=True, exist_ok=True)
    slug = _slugify(item.message)  # type: ignore[attr-defined]
    target = dir_path / f"{slug}.md"

    # Handle slug collisions: allow overwrite if same id, else bump suffix
    counter = 2
    while target.exists():
        existing_text = target.read_text()
        parts = existing_text.split("---", 2)
        if len(parts) >= 3:
            existing_data = yaml.safe_load(parts[1])
            item_id = item.id  # type: ignore[attr-defined]
            if isinstance(existing_data, dict) and str(existing_data.get("id")) == str(item_id):
                break  # overwriting same item
        target = dir_path / f"{slug}-{counter}.md"
        counter += 1

    content = _serialize_md(item)
    fd, tmp = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    os.replace(tmp, target)
    git_commit(target, commit_msg)


def remove_md(dir_path: Path, item_id: str, commit_msg: str) -> bool:
    """Find and delete the .md file whose YAML id matches item_id."""
    if not dir_path.is_dir():
        return False
    for filepath in dir_path.glob("*.md"):
        parts = filepath.read_text().split("---", 2)
        if len(parts) < 3:
            continue
        data = yaml.safe_load(parts[1])
        if isinstance(data, dict) and str(data.get("id")) == item_id:
            filepath.unlink()
            git_rm_commit(filepath, commit_msg)
            return True
    return False


def read_jsonl(filepath: Path, cls: type[T]) -> list[T]:
    """Skips corrupt lines; filters to known dataclass fields for forward compatibility."""
    if not filepath.exists():
        return []
    fields = {f.name for f in dataclasses.fields(cls)}
    result: list[T] = []
    for line in filepath.read_text().splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        data = json.loads(stripped)
        result.append(cls(**{k: v for k, v in data.items() if k in fields}))
    return result


def append_jsonl(filepath: Path, item: T, commit_msg: str) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("a") as f:
        f.write(json.dumps(asdict(item)) + "\n")  # type: ignore[call-overload]
    git_commit(filepath, commit_msg)


def remove_jsonl(filepath: Path, item_id: str, cls: type[T], commit_msg: str) -> bool:
    """Atomic write (temp file + rename) to prevent data loss on concurrent access."""
    items = read_jsonl(filepath, cls)
    filtered = [i for i in items if i.id != item_id]  # type: ignore[attr-defined]
    if len(filtered) == len(items):
        return False
    content = "".join(json.dumps(asdict(i)) + "\n" for i in filtered)  # type: ignore[call-overload]
    fd, tmp = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    os.replace(tmp, filepath)
    git_commit(filepath, commit_msg)
    return True
