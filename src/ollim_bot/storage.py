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
from typing import Any, TypeVar

import yaml

DATA_DIR = Path.home() / ".ollim-bot"
STATE_DIR = DATA_DIR / "state"
DOWNLOADS_DIR = DATA_DIR / "downloads"
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
PID_FILE = STATE_DIR / "bot.pid"

T = TypeVar("T")
log = logging.getLogger(__name__)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def safe_json_load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, UnicodeDecodeError):
        log.warning("Corrupt JSON, using defaults: %s", path)
        return default


def save_attachment(filename: str, data: bytes) -> Path:
    """Handles filename collisions with numeric suffixes."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    target = DOWNLOADS_DIR / filename
    if target.exists():
        stem, suffix = target.stem, target.suffix
        counter = 2
        while (DOWNLOADS_DIR / f"{stem}-{counter}{suffix}").exists():
            counter += 1
        target = DOWNLOADS_DIR / f"{stem}-{counter}{suffix}"
    atomic_write(target, data)
    return target


def _find_repo(filepath: Path) -> Path | None:
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
    """No-op when no git repo is found."""
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


# --- Frontmatter extraction ---


def parse_frontmatter(text: str) -> dict[str, object]:
    """Returns empty dict on any parse failure."""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


# --- Markdown I/O ---


def _slugify(text: str, max_len: int = 50) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
        yaml_key = key.replace("_", "-")
        if isinstance(value, str):
            lines.append(f'{yaml_key}: "{_yaml_escape(value)}"')
        elif isinstance(value, bool):
            lines.append(f"{yaml_key}: {str(value).lower()}")
        elif isinstance(value, list):
            lines.append(f"{yaml_key}:")
            for entry in value:
                if isinstance(entry, str):
                    lines.append(f'  - "{_yaml_escape(entry)}"')
                else:
                    lines.append(f"  - {entry}")
        else:
            lines.append(f"{yaml_key}: {value}")
    lines.append("---")
    lines.append(message)
    return "\n".join(lines) + "\n"


def parse_md(text: str, cls: type[T]) -> T:
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
    for raw_key, value in data.items():
        key = raw_key.replace("-", "_")
        if key not in fields:
            continue
        expected = fields[key].type
        if expected is str or expected == (str | None):
            filtered[key] = str(value) if value is not None else None
        else:
            filtered[key] = value
    filtered["message"] = body
    return cls(**filtered)


def read_md_dir(dir_path: Path, cls: type[T]) -> list[T]:
    if not dir_path.is_dir():
        return []
    result: list[T] = []
    for filepath in sorted(dir_path.glob("*.md")):
        try:
            text = filepath.read_text(encoding="utf-8")
            result.append(parse_md(text, cls))
        except (ValueError, yaml.YAMLError, TypeError, KeyError):
            log.warning("Skipping corrupt file: %s", filepath)
    return result


def write_md(dir_path: Path, item: T, commit_msg: str) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    slug = _slugify(item.message)  # type: ignore[attr-defined]
    target = dir_path / f"{slug}.md"

    # Handle slug collisions: allow overwrite if same id, else bump suffix
    counter = 2
    while target.exists():
        existing_text = target.read_text(encoding="utf-8")
        parts = existing_text.split("---", 2)
        if len(parts) >= 3:
            existing_data = yaml.safe_load(parts[1])
            item_id = item.id  # type: ignore[attr-defined]
            if isinstance(existing_data, dict) and str(existing_data.get("id")) == str(item_id):
                break  # overwriting same item
        target = dir_path / f"{slug}-{counter}.md"
        counter += 1

    content = _serialize_md(item)
    atomic_write(target, content.encode())
    git_commit(target, commit_msg)


def remove_md(dir_path: Path, item_id: str, commit_msg: str) -> bool:
    """Find and delete the .md file whose YAML id matches item_id."""
    if not dir_path.is_dir():
        return False
    for filepath in dir_path.glob("*.md"):
        parts = filepath.read_text(encoding="utf-8").split("---", 2)
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
    for line in filepath.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            log.warning("Skipping corrupt JSONL line in %s", filepath)
            continue
        result.append(cls(**{k: v for k, v in data.items() if k in fields}))
    return result


def append_jsonl(filepath: Path, item: T, commit_msg: str) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(item)) + "\n")  # type: ignore[call-overload]
    git_commit(filepath, commit_msg)


def remove_jsonl(filepath: Path, item_id: str, cls: type[T], commit_msg: str) -> bool:
    items = read_jsonl(filepath, cls)
    filtered = [i for i in items if i.id != item_id]  # type: ignore[attr-defined]
    if len(filtered) == len(items):
        return False
    content = "".join(json.dumps(asdict(i)) + "\n" for i in filtered)  # type: ignore[call-overload]
    atomic_write(filepath, content.encode())
    git_commit(filepath, commit_msg)
    return True
