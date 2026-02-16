"""Shared JSONL I/O and git helpers for persistent data files."""

import dataclasses
import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import TypeVar
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
DATA_DIR = Path.home() / ".ollim-bot"

T = TypeVar("T")


def git_commit(filepath: Path, message: str) -> None:
    """Commit a file if the parent directory is a git repo."""
    repo = filepath.parent
    if not (repo / ".git").is_dir():
        return
    subprocess.run(
        ["git", "add", filepath.name],
        cwd=repo,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--", filepath.name],
        cwd=repo,
        capture_output=True,
    )


def read_jsonl(filepath: Path, cls: type[T]) -> list[T]:
    """Read all entries from a JSONL file into dataclass instances.

    Skips corrupt lines and filters to known dataclass fields.
    """
    if not filepath.exists():
        return []
    fields = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    result: list[T] = []
    for line in filepath.read_text().splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        data = json.loads(stripped)
        result.append(cls(**{k: v for k, v in data.items() if k in fields}))  # type: ignore[call-arg]
    return result


def append_jsonl(filepath: Path, item: T, commit_msg: str) -> None:
    """Append a dataclass instance to a JSONL file and git-commit."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("a") as f:
        f.write(json.dumps(asdict(item)) + "\n")  # type: ignore[call-overload]
    git_commit(filepath, commit_msg)


def remove_jsonl(filepath: Path, item_id: str, cls: type[T], commit_msg: str) -> bool:
    """Remove an entry by ID. Returns True if found.

    Uses atomic write (temp file + rename) to avoid data loss.
    """
    items = read_jsonl(filepath, cls)
    filtered = [i for i in items if i.id != item_id]  # type: ignore[attr-defined]
    if len(filtered) == len(items):
        return False
    content = "".join(json.dumps(asdict(i)) + "\n" for i in filtered)  # type: ignore[call-overload]
    fd, tmp = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    os.write(fd, content.encode())
    os.close(fd)
    os.replace(tmp, filepath)
    git_commit(filepath, commit_msg)
    return True
