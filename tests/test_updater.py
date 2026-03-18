"""Tests for updater.py — auto-update flow."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from unittest.mock import patch

from ollim_bot.updater import apply_update, format_error


def test_apply_update_runs_all_commands(tmp_path: Path) -> None:
    """apply_update must run git pull and uv tool upgrade in order."""
    with patch("ollim_bot.updater.subprocess.run") as mock_run:
        apply_update(tmp_path)

    assert mock_run.call_count == 2
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert cmds == [
        ["git", "pull", "--ff-only"],
        ["uv", "tool", "upgrade", "ollim-bot"],
    ]
    # All commands run in the project directory
    for c in mock_run.call_args_list:
        assert c.kwargs["cwd"] == tmp_path
        assert c.kwargs["check"] is True


def test_apply_update_aborts_on_pull_failure(tmp_path: Path) -> None:
    """If git pull fails, uv sync and tool install must not run."""
    with (
        patch(
            "ollim_bot.updater.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["git", "pull", "--ff-only"]),
        ) as mock_run,
        contextlib.suppress(subprocess.CalledProcessError),
    ):
        apply_update(tmp_path)

    assert mock_run.call_count == 1


def test_apply_update_aborts_on_upgrade_failure(tmp_path: Path) -> None:
    """If uv tool upgrade fails, error propagates."""

    def fail_on_upgrade(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "uv" and cmd[1] == "tool":
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("ollim_bot.updater.subprocess.run", side_effect=fail_on_upgrade) as mock_run,
        contextlib.suppress(subprocess.CalledProcessError),
    ):
        apply_update(tmp_path)

    assert mock_run.call_count == 2
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert cmds == [
        ["git", "pull", "--ff-only"],
        ["uv", "tool", "upgrade", "ollim-bot"],
    ]


def test_format_error_with_str_stderr() -> None:
    """format_error handles str stderr (from text=True subprocess calls)."""
    exc = subprocess.CalledProcessError(1, ["git", "pull", "--ff-only"], stderr="fatal: not a git repo\n")
    result = format_error(exc)
    assert "`git pull --ff-only` returned 1" in result
    assert "fatal: not a git repo" in result


def test_format_error_with_bytes_stderr() -> None:
    """format_error handles bytes stderr (from capture_output without text=True)."""
    exc = subprocess.CalledProcessError(1, ["git", "pull", "--ff-only"], stderr=b"fatal: not a git repo\n")
    result = format_error(exc)
    assert "`git pull --ff-only` returned 1" in result
    assert "fatal: not a git repo" in result


def test_format_error_without_stderr() -> None:
    """format_error works when stderr is None."""
    exc = subprocess.CalledProcessError(1, ["git", "pull", "--ff-only"])
    result = format_error(exc)
    assert result == "`git pull --ff-only` returned 1"


def test_format_error_timeout() -> None:
    """format_error handles TimeoutExpired."""
    exc = subprocess.TimeoutExpired(["git", "fetch", "origin"], timeout=60)
    result = format_error(exc)
    assert result == "`git fetch origin` timed out after 60s"
