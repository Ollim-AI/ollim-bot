"""Tests for _register_routine cron re-registration logic in scheduler.py."""

from unittest.mock import MagicMock

import pytest

from ollim_bot.scheduling import scheduler as scheduler_mod
from ollim_bot.scheduling.routines import Routine


@pytest.fixture(autouse=True)
def _clear_registered_routines():
    scheduler_mod._registered_routines.clear()
    yield
    scheduler_mod._registered_routines.clear()


def _make_routine(routine_id: str = "test1", cron: str = "0 8 * * *") -> Routine:
    return Routine(id=routine_id, message="test message", cron=cron, background=True)


def _make_mocks():
    mock_scheduler = MagicMock()
    mock_agent = MagicMock()
    mock_owner = MagicMock()
    return mock_scheduler, mock_agent, mock_owner


def test_register_routine_adds_to_registry():
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine = _make_routine(cron="0 8 * * *")

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine)

    assert scheduler_mod._registered_routines["test1"] == "0 8 * * *"
    mock_scheduler.add_job.assert_called_once()


def test_register_routine_same_cron_is_noop():
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine = _make_routine(cron="0 8 * * *")

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine)
    mock_scheduler.reset_mock()

    # Same routine, same cron -- should return early
    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine)

    mock_scheduler.add_job.assert_not_called()
    mock_scheduler.get_job.assert_not_called()
    assert scheduler_mod._registered_routines["test1"] == "0 8 * * *"


def test_register_routine_changed_cron_re_registers():
    mock_scheduler, mock_agent, mock_owner = _make_mocks()
    routine_v1 = _make_routine(cron="0 8 * * *")
    routine_v2 = _make_routine(cron="0 12 * * *")

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v1)
    assert scheduler_mod._registered_routines["test1"] == "0 8 * * *"
    mock_scheduler.reset_mock()

    # Simulate get_job returning an existing job
    mock_job = MagicMock()
    mock_scheduler.get_job.return_value = mock_job

    scheduler_mod._register_routine(mock_scheduler, mock_owner, mock_agent, routine_v2)

    # Old job should have been looked up and removed
    mock_scheduler.get_job.assert_called_once_with("routine_test1")
    mock_job.remove.assert_called_once()

    # New job registered with updated cron
    mock_scheduler.add_job.assert_called_once()
    assert scheduler_mod._registered_routines["test1"] == "0 12 * * *"


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
    assert scheduler_mod._registered_routines["test1"] == "30 9 * * *"
