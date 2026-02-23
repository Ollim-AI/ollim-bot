"""Tests for scheduler.py prompt-building and cron conversion."""

from ollim_bot.forks import BgForkConfig
from ollim_bot.scheduling.reminders import Reminder
from ollim_bot.scheduling.routines import Routine
from ollim_bot.scheduling.scheduler import (
    _build_bg_preamble,
    _build_reminder_prompt,
    _build_routine_prompt,
    _convert_dow,
)


def test_routine_prompt_foreground():
    routine = Routine(id="abc", message="Morning briefing", cron="0 8 * * *")

    prompt = _build_routine_prompt(routine, reminders=[], routines=[])

    assert prompt == "[routine:abc] Morning briefing"


def test_routine_prompt_background():
    routine = Routine(
        id="def", message="Silent check", cron="0 8 * * *", background=True
    )

    prompt = _build_routine_prompt(routine, reminders=[], routines=[])

    assert prompt.startswith("[routine-bg:def]")
    assert "ping_user" in prompt
    assert "Silent check" in prompt


def test_reminder_prompt_plain():
    reminder = Reminder(
        id="r1", message="Take a break", run_at="2026-02-16T12:00:00-08:00"
    )

    prompt = _build_reminder_prompt(reminder, reminders=[], routines=[])

    assert "[reminder:r1]" in prompt
    assert "Take a break" in prompt
    assert "CHAIN" not in prompt


def test_reminder_prompt_background():
    reminder = Reminder(
        id="r2",
        message="Check tasks",
        run_at="2026-02-16T12:00:00-08:00",
        background=True,
    )

    prompt = _build_reminder_prompt(reminder, reminders=[], routines=[])

    assert "[reminder-bg:r2]" in prompt
    assert "ping_user" in prompt


def test_reminder_prompt_chain_mid():
    reminder = Reminder(
        id="r3",
        message="Is task done?",
        run_at="2026-02-16T12:00:00-08:00",
        chain_depth=1,
        max_chain=3,
    )

    prompt = _build_reminder_prompt(reminder, reminders=[], routines=[])

    assert "CHAIN CONTEXT" in prompt
    assert "check 2 of 4" in prompt
    assert "follow_up_chain" in prompt
    assert "available" in prompt
    assert "FINAL" not in prompt


def test_reminder_prompt_chain_final():
    reminder = Reminder(
        id="r4",
        message="Last check",
        run_at="2026-02-16T12:00:00-08:00",
        chain_depth=2,
        max_chain=2,
    )

    prompt = _build_reminder_prompt(reminder, reminders=[], routines=[])

    assert "CHAIN CONTEXT" in prompt
    assert "FINAL check" in prompt
    assert "check 3 of 3" in prompt
    assert "NOT available" in prompt


def test_reminder_prompt_chain_first():
    reminder = Reminder(
        id="r5",
        message="First check",
        run_at="2026-02-16T12:00:00-08:00",
        chain_depth=0,
        max_chain=2,
    )

    prompt = _build_reminder_prompt(reminder, reminders=[], routines=[])

    assert "check 1 of 3" in prompt
    assert "follow_up_chain" in prompt


def test_bg_routine_prompt_includes_budget(data_dir):
    from datetime import date

    from ollim_bot import ping_budget

    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=10, used=3, critical_used=1, last_reset=date.today().isoformat()
        )
    )
    routine = Routine(
        id="abc", message="Check tasks", cron="0 8 * * *", background=True
    )

    prompt = _build_routine_prompt(routine, reminders=[], routines=[routine])

    assert "7/10 remaining today" in prompt
    assert "1 bg routine" in prompt


def test_bg_reminder_prompt_includes_budget(data_dir):
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from ollim_bot import ping_budget

    tz = ZoneInfo("America/Los_Angeles")
    now = datetime.now(tz)
    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=10, used=5, critical_used=0, last_reset=date.today().isoformat()
        )
    )
    reminder = Reminder(
        id="r1", message="Check email", run_at=now.isoformat(), background=True
    )

    prompt = _build_reminder_prompt(reminder, reminders=[reminder], routines=[])

    assert "5/10 remaining today" in prompt


def test_fg_routine_prompt_unchanged(data_dir):
    routine = Routine(id="abc", message="Morning briefing", cron="0 8 * * *")

    prompt = _build_routine_prompt(routine, reminders=[], routines=[])

    assert prompt == "[routine:abc] Morning briefing"
    assert "budget" not in prompt.lower()


def test_convert_dow_weekdays():
    assert _convert_dow("1-5") == "mon-fri"


def test_convert_dow_star():
    assert _convert_dow("*") == "*"


def test_convert_dow_star_step():
    assert _convert_dow("*/2") == "*/2"


def test_convert_dow_sunday_zero():
    assert _convert_dow("0") == "sun"


def test_convert_dow_sunday_seven():
    assert _convert_dow("7") == "sun"


def test_convert_dow_list():
    assert _convert_dow("1,3,5") == "mon,wed,fri"


def test_convert_dow_range_with_step():
    assert _convert_dow("1-5/2") == "mon-fri/2"


# --- Busy-aware preamble ---


def test_bg_preamble_normal_no_busy_line():
    result = _build_bg_preamble([], [])
    assert "mid-conversation" not in result
    assert "report_updates" in result


def test_bg_preamble_busy_includes_quiet_instruction():
    result = _build_bg_preamble([], [], busy=True)
    assert "mid-conversation" in result
    assert "report_updates" in result
    assert "critical" in result.lower()


def test_bg_routine_prompt_busy(data_dir):
    routine = Routine(
        id="abc", message="Check tasks", cron="0 8 * * *", background=True
    )

    prompt = _build_routine_prompt(routine, reminders=[], routines=[], busy=True)

    assert "mid-conversation" in prompt
    assert "Check tasks" in prompt


def test_bg_reminder_prompt_busy(data_dir):
    reminder = Reminder(
        id="r1",
        message="Check email",
        run_at="2026-02-16T12:00:00-08:00",
        background=True,
    )

    prompt = _build_reminder_prompt(reminder, reminders=[], routines=[], busy=True)

    assert "mid-conversation" in prompt
    assert "Check email" in prompt


# --- BgForkConfig-aware preamble ---


def test_bg_preamble_allow_ping_false():
    config = BgForkConfig(allow_ping=False)

    result = _build_bg_preamble([], [], bg_config=config)

    assert "disabled" in result.lower()
    assert "not available" in result.lower()
    assert "Ping budget" not in result


def test_bg_preamble_update_always():
    config = BgForkConfig(update_main_session="always")

    result = _build_bg_preamble([], [], bg_config=config)

    assert "MUST" in result
    assert "report_updates" in result


def test_bg_preamble_update_freely():
    config = BgForkConfig(update_main_session="freely")

    result = _build_bg_preamble([], [], bg_config=config)

    assert "optionally" in result.lower()
    assert "report_updates" in result


def test_bg_preamble_update_blocked():
    config = BgForkConfig(update_main_session="blocked")

    result = _build_bg_preamble([], [], bg_config=config)

    assert "silently" in result.lower()
    assert "report_updates" not in result.split("silently")[1]


def test_bg_preamble_default_config_unchanged():
    """Default config produces preamble with ping_user and report_updates."""
    config = BgForkConfig()

    result = _build_bg_preamble([], [], bg_config=config)

    assert "ping_user" in result
    assert "report_updates" in result
    assert "what happened" in result
