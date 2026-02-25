"""Tests for ping_budget.py — refill-on-read ping budget."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pytest import approx

from ollim_bot import ping_budget
from ollim_bot.ping_budget import BudgetState

TZ = ZoneInfo("America/Los_Angeles")


def test_load_returns_defaults_when_no_file(data_dir):
    state = ping_budget.load()

    assert state.capacity == 5
    assert state.available == 5.0
    assert state.refill_rate_minutes == 90
    assert state.critical_used == 0
    assert state.daily_used == 0


def test_save_and_load_roundtrip(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=3.0,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=1,
        critical_reset_date=date.today().isoformat(),
        daily_used=2,
        daily_used_reset=date.today().isoformat(),
    )

    ping_budget.save(state)
    loaded = ping_budget.load()

    assert loaded.capacity == 5
    assert loaded.available >= 3.0  # may have tiny refill from elapsed
    assert loaded.critical_used == 1
    assert loaded.daily_used == 2


def test_load_refills_based_on_elapsed_time(data_dir):
    two_hours_ago = datetime.now(TZ) - timedelta(hours=2)
    state = BudgetState(
        capacity=5,
        available=1.0,
        refill_rate_minutes=60,
        last_refill=two_hours_ago.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=4,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    loaded = ping_budget.load()

    assert loaded.available == approx(3.0, abs=0.01)  # 1.0 + 2h/60min = 3.0


def test_load_refill_caps_at_capacity(data_dir):
    long_ago = datetime.now(TZ) - timedelta(hours=24)
    state = BudgetState(
        capacity=5,
        available=0.0,
        refill_rate_minutes=60,
        last_refill=long_ago.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=10,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    loaded = ping_budget.load()

    assert loaded.available == 5.0


def test_load_resets_daily_counters_on_stale_date(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=2.0,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=3,
        critical_reset_date="2025-01-01",
        daily_used=8,
        daily_used_reset="2025-01-01",
    )
    ping_budget.save(state)

    loaded = ping_budget.load()

    assert loaded.critical_used == 0
    assert loaded.daily_used == 0
    assert loaded.critical_reset_date == date.today().isoformat()
    assert loaded.daily_used_reset == date.today().isoformat()


def test_try_use_decrements(data_dir):
    ping_budget.load()

    result = ping_budget.try_use()

    assert result is True
    state = ping_budget.load()
    assert state.available >= 3.0  # 5 - 1 = 4, plus tiny refill
    assert state.daily_used == 1


def test_try_use_returns_false_when_empty(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=0.5,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=5,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    result = ping_budget.try_use()

    assert result is False


def test_try_use_succeeds_after_refill(data_dir):
    ninety_min_ago = datetime.now(TZ) - timedelta(minutes=90)
    state = BudgetState(
        capacity=5,
        available=0.0,
        refill_rate_minutes=90,
        last_refill=ninety_min_ago.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=5,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    result = ping_budget.try_use()

    assert result is True  # refilled 1.0, then spent it


def test_record_critical_increments(data_dir):
    ping_budget.load()

    ping_budget.record_critical()

    state = ping_budget.load()
    assert state.critical_used == 1


def test_set_capacity_updates(data_dir):
    ping_budget.load()

    ping_budget.set_capacity(7)

    state = ping_budget.load()
    assert state.capacity == 7


def test_set_refill_rate_updates(data_dir):
    ping_budget.load()

    ping_budget.set_refill_rate(60)

    state = ping_budget.load()
    assert state.refill_rate_minutes == 60


def test_get_status_at_capacity(data_dir):
    ping_budget.load()

    status = ping_budget.get_status()

    assert "5/5 available" in status
    assert "refills 1 every 90 min" in status
    assert "next in" not in status  # at capacity, no refill line


def test_get_status_below_capacity(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=3.0,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=0,
        critical_reset_date=date.today().isoformat(),
        daily_used=2,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    status = ping_budget.get_status()

    assert "3/5 available" in status
    assert "next in" in status


def test_get_status_shows_daily_used(data_dir):
    now = datetime.now(TZ)
    state = BudgetState(
        capacity=5,
        available=5.0,
        refill_rate_minutes=90,
        last_refill=now.isoformat(),
        critical_used=1,
        critical_reset_date=date.today().isoformat(),
        daily_used=3,
        daily_used_reset=date.today().isoformat(),
    )
    ping_budget.save(state)

    status = ping_budget.get_full_status()

    assert "3 used today" in status
    assert "1 critical" in status
