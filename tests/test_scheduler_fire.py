"""Tests for _register_routine re-registration logic in scheduler.py."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from ollim_bot.config import TZ
from ollim_bot.scheduling import scheduler as scheduler_mod
from ollim_bot.scheduling.reminders import Reminder
from ollim_bot.scheduling.routines import Routine


@pytest.fixture(autouse=True)
def _clear_registered_routines():
    scheduler_mod._registered_routines.clear()
    yield
    scheduler_mod._registered_routines.clear()


def _make_routine(
    routine_id: str = "test1",
    cron: str = "0 8 * * *",
    **kwargs: Any,
) -> Routine:
    return Routine(id=routine_id, message="test message", cron=cron, background=True, **kwargs)


def _make_mocks():
    mock_scheduler = MagicMock()
    mock_agent = MagicMock()
    mock_owner = MagicMock()
    return mock_scheduler, mock_agent, mock_owner


def test_register_routine_adds_to_registry():
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine = _make_routine(cron="0 8 * * *")

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine)

    assert scheduler_mod._registered_routines["test1"] == routine
    mock_scheduler.add_job.assert_called_once()


def test_register_routine_same_routine_is_noop():
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine = _make_routine(cron="0 8 * * *")

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine)
    mock_scheduler.reset_mock()

    # Same routine object — should return early
    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine)

    mock_scheduler.add_job.assert_not_called()
    mock_scheduler.get_job.assert_not_called()


def test_register_routine_changed_cron_re_registers():
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine_v1 = _make_routine(cron="0 8 * * *")
    routine_v2 = _make_routine(cron="0 12 * * *")

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v1)
    mock_scheduler.reset_mock()

    mock_job = MagicMock()
    mock_scheduler.get_job.return_value = mock_job

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v2)

    mock_scheduler.get_job.assert_called_once_with("routine_test1")
    mock_job.remove.assert_called_once()
    mock_scheduler.add_job.assert_called_once()
    assert scheduler_mod._registered_routines["test1"] == routine_v2


def test_register_routine_changed_cron_missing_job():
    """When cron changes but get_job returns None, removal is skipped gracefully."""
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine_v1 = _make_routine(cron="0 8 * * *")
    routine_v2 = _make_routine(cron="30 9 * * *")

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v1)
    mock_scheduler.reset_mock()

    mock_scheduler.get_job.return_value = None

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v2)

    mock_scheduler.get_job.assert_called_once_with("routine_test1")
    mock_scheduler.add_job.assert_called_once()
    assert scheduler_mod._registered_routines["test1"] == routine_v2


def test_register_routine_changed_non_cron_field_re_registers():
    """Non-cron field changes (model, allowed_tools, etc.) trigger re-registration."""
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine_v1 = _make_routine()
    routine_v2 = _make_routine(model="haiku")

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v1)
    mock_scheduler.reset_mock()

    mock_job = MagicMock()
    mock_scheduler.get_job.return_value = mock_job

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v2)

    mock_job.remove.assert_called_once()
    mock_scheduler.add_job.assert_called_once()
    assert scheduler_mod._registered_routines["test1"] == routine_v2


def test_register_routine_changed_allowed_tools_re_registers():
    """Changing allowed_tools triggers re-registration."""
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine_v1 = _make_routine()
    routine_v2 = _make_routine(allowed_tools=["Write", "Edit"])

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v1)
    mock_scheduler.reset_mock()

    mock_job = MagicMock()
    mock_scheduler.get_job.return_value = mock_job

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v2)

    mock_job.remove.assert_called_once()
    mock_scheduler.add_job.assert_called_once()
    assert scheduler_mod._registered_routines["test1"] == routine_v2


@pytest.mark.asyncio
async def test_reminder_fire_invalid_tools_cleans_up(monkeypatch):
    """When validate_dispatch fails at fire time, the reminder file and registry entry are cleaned."""
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    mock_agent.lock.return_value = MagicMock(locked=MagicMock(return_value=False))
    reminder = Reminder(
        id="bad",
        message="test",
        run_at=(datetime.now(TZ) + timedelta(minutes=5)).isoformat(),
        background=True,
        allowed_tools=["Bash(*)"],  # invalid — too broad
    )

    remove_calls: list[str] = []
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.remove_reminder",
        lambda rid: remove_calls.append(rid) or True,
    )
    scheduler_mod._registered_reminders.clear()
    try:
        scheduler_mod._register_reminder(mock_scheduler, mock_owner, mock_agent, reminder)
        assert "bad" in scheduler_mod._registered_reminders
        fire_oneshot = mock_scheduler.add_job.call_args[0][0]

        await fire_oneshot()

        assert remove_calls == ["bad"]
        assert "bad" not in scheduler_mod._registered_reminders
    finally:
        scheduler_mod._registered_reminders.clear()


def test_register_routine_changed_message_re_registers():
    """Changing the message body triggers re-registration."""
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine_v1 = _make_routine()
    routine_v2 = Routine(id="test1", message="updated instructions", cron="0 8 * * *", background=True)

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v1)
    mock_scheduler.reset_mock()

    mock_job = MagicMock()
    mock_scheduler.get_job.return_value = mock_job

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v2)

    mock_job.remove.assert_called_once()
    mock_scheduler.add_job.assert_called_once()
