"""Tests for updater.py — semver-aware auto-update flow."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ollim_bot.updater import (
    UpdateStatus,
    _get_current_version,
    _parse_semver,
    apply_update,
    check_for_updates,
    format_error,
    format_version_string,
)

# --- _parse_semver ---


def test_parse_semver_valid() -> None:
    assert _parse_semver("v1.2.3") == (1, 2, 3)
    assert _parse_semver("0.1.0") == (0, 1, 0)


def test_parse_semver_invalid() -> None:
    with pytest.raises(ValueError, match="not a valid semver tag"):
        _parse_semver("not-a-version")


def test_parse_semver_strips_v_prefix() -> None:
    assert _parse_semver("v1.0.0") == _parse_semver("1.0.0")


def test_parse_semver_prerelease_raises() -> None:
    with pytest.raises(ValueError, match="not a valid semver tag"):
        _parse_semver("v1.0.0-rc1")


def test_version_comparison() -> None:
    assert _parse_semver("v0.2.0") > _parse_semver("v0.1.0")
    assert _parse_semver("v1.0.0") > _parse_semver("v0.99.99")
    assert _parse_semver("v0.1.0") == _parse_semver("v0.1.0")


# --- __version__ ---


def test_version_attribute_exists() -> None:
    import importlib.metadata

    from ollim_bot import __version__

    assert __version__ == importlib.metadata.version("ollim-bot")


# --- _get_current_version ---


def test_get_current_version_from_git_describe(tmp_path: Path) -> None:
    with patch("ollim_bot.updater.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="v0.2.0\n")

        result = _get_current_version(tmp_path)

    assert result == "v0.2.0"


def test_get_current_version_falls_back_to_metadata(tmp_path: Path) -> None:
    with (
        patch(
            "ollim_bot.updater.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, ["git", "describe"]),
        ),
        patch("ollim_bot.updater.importlib.metadata.version", return_value="0.1.0"),
    ):
        result = _get_current_version(tmp_path)

    assert result == "0.1.0"


# --- check_for_updates ---


def _mock_git_for_update_check(
    *,
    current_tag: str = "v0.1.0",
    latest_tag: str = "v0.2.0",
    log_output: str = "abc1234 feat: new feature",
) -> contextlib.AbstractContextManager[object]:
    """Return a patch that mocks subprocess.run for check_for_updates."""

    def side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["git", "fetch", "origin"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[:2] == ["git", "describe"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{current_tag}\n")
        if cmd[:2] == ["git", "tag"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{latest_tag}\n")
        if cmd[:2] == ["git", "log"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{log_output}\n")
        return subprocess.CompletedProcess(cmd, 0)

    return patch("ollim_bot.updater.subprocess.run", side_effect=side_effect)


def test_check_for_updates_detects_new_tag(tmp_path: Path) -> None:
    with _mock_git_for_update_check(
        current_tag="v0.1.0",
        latest_tag="v0.2.0",
        log_output="abc1234 feat: new feature",
    ):
        status = check_for_updates(tmp_path)

    assert status == UpdateStatus(
        available=True,
        current_version="v0.1.0",
        latest_version="v0.2.0",
        commit_summary="abc1234 feat: new feature",
    )


def test_check_for_updates_no_new_tag(tmp_path: Path) -> None:
    with _mock_git_for_update_check(current_tag="v0.2.0", latest_tag="v0.2.0"):
        status = check_for_updates(tmp_path)

    assert status.available is False
    assert status.current_version == "v0.2.0"
    assert status.latest_version == "v0.2.0"


def test_check_for_updates_no_tags_exist(tmp_path: Path) -> None:
    """When no tags exist, git describe fails and git tag -l returns empty."""

    def side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["git", "fetch", "origin"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[:2] == ["git", "describe"]:
            raise subprocess.CalledProcessError(128, cmd)
        if cmd[:2] == ["git", "tag"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="\n")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("ollim_bot.updater.subprocess.run", side_effect=side_effect),
        patch("ollim_bot.updater.importlib.metadata.version", return_value="0.1.0"),
    ):
        status = check_for_updates(tmp_path)

    assert status.available is False


def test_check_for_updates_malformed_tag(tmp_path: Path) -> None:
    """Malformed tags cause ValueError — caught internally, returns available=False."""
    with _mock_git_for_update_check(current_tag="v0.1.0", latest_tag="not-semver"):
        status = check_for_updates(tmp_path)

    assert status.available is False


def test_check_for_updates_commit_summary_range(tmp_path: Path) -> None:
    """Verify commit_summary uses the correct tag range."""
    calls: list[list[str]] = []

    def side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:3] == ["git", "fetch", "origin"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[:2] == ["git", "describe"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="v0.1.0\n")
        if cmd[:2] == ["git", "tag"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="v0.2.0\n")
        if cmd[:2] == ["git", "log"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="changes\n")
        return subprocess.CompletedProcess(cmd, 0)

    with patch("ollim_bot.updater.subprocess.run", side_effect=side_effect):
        check_for_updates(tmp_path)

    log_calls = [c for c in calls if c[:2] == ["git", "log"]]
    assert len(log_calls) == 1
    assert "v0.1.0..v0.2.0" in log_calls[0]


# --- format_version_string ---


def test_format_version_string_tagged(tmp_path: Path) -> None:
    with patch("ollim_bot.updater.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="v0.2.0\n")

        result = format_version_string(tmp_path)

    assert result == "ollim-bot v0.2.0"


def test_format_version_string_dev(tmp_path: Path) -> None:
    with patch("ollim_bot.updater.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="v0.1.0-3-gabc1234\n")

        result = format_version_string(tmp_path)

    assert result == "ollim-bot v0.1.0+dev (abc1234)"


def test_format_version_string_git_failure(tmp_path: Path) -> None:
    with (
        patch(
            "ollim_bot.updater.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, ["git", "describe"]),
        ),
        patch("ollim_bot.updater.importlib.metadata.version", return_value="0.1.0"),
    ):
        result = format_version_string(tmp_path)

    assert result == "ollim-bot v0.1.0"


# --- apply_update (existing tests) ---


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


# --- format_error (existing tests) ---


def test_format_error_with_str_stderr() -> None:
    exc = subprocess.CalledProcessError(1, ["git", "pull", "--ff-only"], stderr="fatal: not a git repo\n")
    result = format_error(exc)
    assert "`git pull --ff-only` returned 1" in result
    assert "fatal: not a git repo" in result


def test_format_error_with_bytes_stderr() -> None:
    exc = subprocess.CalledProcessError(1, ["git", "pull", "--ff-only"], stderr=b"fatal: not a git repo\n")
    result = format_error(exc)
    assert "`git pull --ff-only` returned 1" in result
    assert "fatal: not a git repo" in result


def test_format_error_without_stderr() -> None:
    exc = subprocess.CalledProcessError(1, ["git", "pull", "--ff-only"])
    result = format_error(exc)
    assert result == "`git pull --ff-only` returned 1"


def test_format_error_timeout() -> None:
    exc = subprocess.TimeoutExpired(["git", "fetch", "origin"], timeout=60)
    result = format_error(exc)
    assert result == "`git fetch origin` timed out after 60s"
