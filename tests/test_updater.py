"""Tests for updater.py — auto-update flow."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from unittest.mock import patch

from ollim_bot.updater import apply_update


def test_apply_update_runs_all_commands(tmp_path: Path) -> None:
    """apply_update must run git pull, uv sync, and uv tool install in order."""
    with patch("ollim_bot.updater.subprocess.run") as mock_run:
        apply_update(tmp_path)

    assert mock_run.call_count == 3
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert cmds == [
        ["git", "pull", "--ff-only"],
        ["uv", "sync"],
        ["uv", "tool", "install", "--editable", "."],
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


def test_apply_update_aborts_on_sync_failure(tmp_path: Path) -> None:
    """If uv sync fails, tool install must not run."""

    def fail_on_sync(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "uv" and cmd[1] == "sync":
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("ollim_bot.updater.subprocess.run", side_effect=fail_on_sync) as mock_run,
        contextlib.suppress(subprocess.CalledProcessError),
    ):
        apply_update(tmp_path)

    assert mock_run.call_count == 2
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert cmds == [
        ["git", "pull", "--ff-only"],
        ["uv", "sync"],
    ]
