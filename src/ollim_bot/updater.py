"""Git-based auto-update: fetch, compare, pull, sync, restart."""

from __future__ import annotations

import logging
import os
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
    local_sha: str
    remote_sha: str
    commit_summary: str


def _get_remote_ref(project_dir: Path) -> str:
    """Resolve the remote tracking ref for the current branch."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=_LOCAL_GIT_TIMEOUT,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "origin/main"


def check_for_updates(project_dir: Path) -> UpdateStatus:
    """Fetch from origin and compare HEAD to the tracking branch.

    Sync — run via asyncio.to_thread from the scheduler.
    """
    subprocess.run(
        ["git", "fetch", "origin"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        timeout=_GIT_TIMEOUT,
    )

    local_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        text=True,
        timeout=_LOCAL_GIT_TIMEOUT,
    ).stdout.strip()

    remote_ref = _get_remote_ref(project_dir)
    remote_sha = subprocess.run(
        ["git", "rev-parse", remote_ref],
        cwd=project_dir,
        capture_output=True,
        check=True,
        text=True,
        timeout=_LOCAL_GIT_TIMEOUT,
    ).stdout.strip()

    if local_sha == remote_sha:
        return UpdateStatus(
            available=False,
            local_sha=local_sha,
            remote_sha=remote_sha,
            commit_summary="",
        )

    summary = subprocess.run(
        ["git", "log", "--oneline", f"{local_sha}..{remote_sha}"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        text=True,
        timeout=_LOCAL_GIT_TIMEOUT,
    ).stdout.strip()

    return UpdateStatus(
        available=True,
        local_sha=local_sha,
        remote_sha=remote_sha,
        commit_summary=summary,
    )


def apply_update(project_dir: Path) -> None:
    """Pull latest changes (fast-forward only) and sync dependencies.

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
        ["uv", "sync"],
        cwd=project_dir,
        capture_output=True,
        check=True,
        timeout=_UV_SYNC_TIMEOUT,
    )


def format_error(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired) -> str:
    """Human-readable error message for a failed subprocess call."""
    cmd = shlex.join(exc.cmd) if isinstance(exc.cmd, list) else exc.cmd
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"`{cmd}` timed out after {exc.timeout}s"
    return f"`{cmd}` returned {exc.returncode}"


def restart_process() -> None:
    """Replace the current process with a fresh one via os.execv.

    Deletes the PID file first — os.execv keeps the same PID and skips
    atexit handlers, so _check_already_running() would otherwise see a
    stale PID file matching the current PID and refuse to start.
    """
    PID_FILE.unlink(missing_ok=True)
    os.execv(sys.executable, [sys.executable, *sys.argv])
