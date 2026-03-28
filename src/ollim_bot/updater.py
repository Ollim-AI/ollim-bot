# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Semver-aware auto-update: fetch tags, compare versions, pull, sync, restart."""

from __future__ import annotations

import importlib.metadata
import logging
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ollim_bot.storage import PID_FILE

log = logging.getLogger(__name__)

_GIT_TIMEOUT = 60
_LOCAL_GIT_TIMEOUT = 10
_UV_SYNC_TIMEOUT = 300


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    available: bool
    current_version: str
    latest_version: str
    commit_summary: str


def _parse_semver(tag: str) -> tuple[int, int, int]:
    """Strip leading 'v', split on '.', return (major, minor, patch).

    Raises ValueError on malformed tags (including pre-release suffixes).
    """
    cleaned = tag.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", cleaned):
        raise ValueError(f"not a valid semver tag: {tag!r}")
    parts = cleaned.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _get_current_version(project_dir: Path) -> str:
    """Get the nearest ancestor tag reachable from HEAD (by commit distance).

    Falls back to importlib.metadata if no tags exist (fresh clone before
    first release). Uses importlib.metadata directly to avoid circular imports.
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=project_dir,
            capture_output=True,
            check=True,
            text=True,
            timeout=_LOCAL_GIT_TIMEOUT,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return importlib.metadata.version("ollim-bot")


def _get_latest_tag(project_dir: Path) -> str | None:
    """Return the latest semver tag (by version sort), or None if no tags."""
    result = subprocess.run(
        ["git", "tag", "-l", "v*", "--sort=-version:refname"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        text=True,
        timeout=_LOCAL_GIT_TIMEOUT,
    )
    first_line = result.stdout.strip().split("\n")[0].strip()
    return first_line or None


def check_for_updates(project_dir: Path) -> UpdateStatus:
    """Fetch tags from origin and compare current version to latest tag.

    Sync — run via asyncio.to_thread from the scheduler.
    """
    subprocess.run(
        ["git", "fetch", "origin", "--tags"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        timeout=_GIT_TIMEOUT,
    )

    current = _get_current_version(project_dir)
    latest = _get_latest_tag(project_dir)

    if latest is None:
        return UpdateStatus(
            available=False,
            current_version=current,
            latest_version=current,
            commit_summary="",
        )

    try:
        update_available = _parse_semver(latest) > _parse_semver(current)
    except ValueError:
        log.warning("auto-update: malformed semver tag (current=%r, latest=%r)", current, latest)
        return UpdateStatus(
            available=False,
            current_version=current,
            latest_version=current,
            commit_summary="",
        )

    if not update_available:
        return UpdateStatus(
            available=False,
            current_version=current,
            latest_version=latest,
            commit_summary="",
        )

    summary = subprocess.run(
        ["git", "log", "--oneline", f"{current}..{latest}"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        text=True,
        timeout=_LOCAL_GIT_TIMEOUT,
    ).stdout.strip()

    return UpdateStatus(
        available=True,
        current_version=current,
        latest_version=latest,
        commit_summary=summary,
    )


def apply_update(project_dir: Path) -> None:
    """Pull latest changes (fast-forward only) and upgrade tool dependencies.

    Sync — run via asyncio.to_thread from the scheduler.
    """
    subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        timeout=_GIT_TIMEOUT,
    )
    subprocess.run(
        ["uv", "tool", "upgrade", "ollim-bot"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        timeout=_UV_SYNC_TIMEOUT,
    )


def format_version_string(project_dir: Path) -> str:
    """Build a human-readable version string for display.

    Uses a single `git describe --tags` call: clean output (e.g. "v0.2.0")
    means HEAD is on a tag; suffixed output (e.g. "v0.1.0-3-gabc1234") means
    a dev build. Falls back to importlib.metadata on git failure.
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags"],
            cwd=project_dir,
            capture_output=True,
            check=True,
            text=True,
            timeout=_LOCAL_GIT_TIMEOUT,
        )
        desc = result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return f"ollim-bot v{importlib.metadata.version('ollim-bot')}"

    match = re.match(r"^(v\d+\.\d+\.\d+)-\d+-g([0-9a-f]+)$", desc)
    if match:
        return f"ollim-bot {match.group(1)}+dev ({match.group(2)})"
    return f"ollim-bot {desc}"


def format_error(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired) -> str:
    cmd = shlex.join(exc.cmd) if isinstance(exc.cmd, list) else exc.cmd
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"`{cmd}` timed out after {exc.timeout}s"
    msg = f"`{cmd}` returned {exc.returncode}"
    if exc.stderr:
        stderr = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode(errors="replace")
        stderr = stderr.strip()
        if stderr:
            msg += f"\n```\n{stderr}\n```"
    return msg


def format_commit_summary(commit_summary: str, *, max_lines: int = 5) -> str:
    lines = commit_summary.splitlines()
    summary = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        summary += f"\n... and {len(lines) - max_lines} more"
    return summary


def log_and_restart() -> None:
    from ollim_bot.sessions import load_session_id, log_session_event

    session_id = load_session_id()
    if session_id:
        log_session_event(session_id, "restarting")
    restart_process()


def restart_process() -> None:
    """Replace the current process with a fresh one.

    Deletes the PID file first — os.execv keeps the same PID and skips
    atexit handlers, so _check_already_running() would otherwise see a
    stale PID file matching the current PID and refuse to start.

    On Windows, os.execv spawns a child instead of replacing the process,
    so we use subprocess.Popen + sys.exit to avoid duplicate instances.
    """
    PID_FILE.unlink(missing_ok=True)
    if sys.platform == "win32":
        subprocess.Popen(sys.argv)
        os._exit(0)  # Skip atexit (mirrors os.execv behavior on Unix)
    os.execv(sys.executable, [sys.executable, *sys.argv])
