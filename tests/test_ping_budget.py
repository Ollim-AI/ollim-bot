"""Tests for ping_budget.py — daily ping budget tracking."""

from datetime import date

from ollim_bot import ping_budget
from ollim_bot.ping_budget import BudgetState


def test_load_returns_defaults_when_no_file(data_dir):
    state = ping_budget.load()

    assert state.daily_limit == 10
    assert state.used == 0
    assert state.critical_used == 0
    assert state.last_reset == date.today().isoformat()


def test_save_and_load_roundtrip(data_dir):
    state = BudgetState(
        daily_limit=5, used=2, critical_used=1, last_reset=date.today().isoformat()
    )

    ping_budget.save(state)
    loaded = ping_budget.load()

    assert loaded == state


def test_load_resets_on_stale_date(data_dir):
    stale = BudgetState(
        daily_limit=15, used=7, critical_used=3, last_reset="2025-01-01"
    )
    ping_budget.save(stale)

    loaded = ping_budget.load()

    assert loaded.used == 0
    assert loaded.critical_used == 0
    assert loaded.daily_limit == 15
    assert loaded.last_reset == date.today().isoformat()


def test_try_use_decrements(data_dir):
    ping_budget.load()  # ensure file exists

    result = ping_budget.try_use()

    assert result is True
    assert ping_budget.load().used == 1


def test_try_use_returns_false_when_exhausted(data_dir):
    exhausted = BudgetState(
        daily_limit=10, used=10, critical_used=0, last_reset=date.today().isoformat()
    )
    ping_budget.save(exhausted)

    result = ping_budget.try_use()

    assert result is False
    assert ping_budget.load().used == 10


def test_record_critical_increments(data_dir):
    ping_budget.load()  # ensure file exists

    ping_budget.record_critical()

    state = ping_budget.load()
    assert state.critical_used == 1
    assert state.used == 0


def test_set_limit_updates_and_persists(data_dir):
    original = BudgetState(
        daily_limit=10, used=3, critical_used=1, last_reset=date.today().isoformat()
    )
    ping_budget.save(original)

    ping_budget.set_limit(20)

    state = ping_budget.load()
    assert state.daily_limit == 20
    assert state.used == 3


def test_get_status_fresh(data_dir):
    ping_budget.load()  # ensure defaults

    status = ping_budget.get_status()

    assert "10/10 remaining today" in status


def test_get_status_after_use(data_dir):
    state = BudgetState(
        daily_limit=10, used=3, critical_used=1, last_reset=date.today().isoformat()
    )
    ping_budget.save(state)

    status = ping_budget.get_status()

    assert "7/10 remaining today" in status
    assert "3 used" in status
    assert "1 critical" in status
