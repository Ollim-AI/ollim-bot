"""Tests for scheduler.py prompt-building and cron conversion."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ollim_bot.forks import BgForkConfig
from ollim_bot.scheduling.reminders import Reminder
from ollim_bot.scheduling.routines import Routine
from ollim_bot.scheduling.scheduler import (
    ScheduleEntry,
    _build_bg_preamble,
    _build_reminder_prompt,
    _build_routine_prompt,
    _build_upcoming_schedule,
    _convert_dow,
    _fires_before_midnight,
    _remaining_bg_routine_firings,
)

TZ = ZoneInfo("America/Los_Angeles")


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
    result = _build_bg_preamble(0, 0)
    assert "mid-conversation" not in result
    assert "report_updates" in result


def test_bg_preamble_busy_includes_quiet_instruction():
    result = _build_bg_preamble(0, 0, busy=True)
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

    result = _build_bg_preamble(0, 0, bg_config=config)

    assert "disabled" in result.lower()
    assert "not available" in result.lower()
    assert "Ping budget" not in result


def test_bg_preamble_update_always():
    config = BgForkConfig(update_main_session="always")

    result = _build_bg_preamble(0, 0, bg_config=config)

    assert "MUST" in result
    assert "report_updates" in result


def test_bg_preamble_update_freely():
    config = BgForkConfig(update_main_session="freely")

    result = _build_bg_preamble(0, 0, bg_config=config)

    assert "optionally" in result.lower()
    assert "report_updates" in result


def test_bg_preamble_update_blocked():
    config = BgForkConfig(update_main_session="blocked")

    result = _build_bg_preamble(0, 0, bg_config=config)

    assert "silently" in result.lower()
    assert "report_updates" not in result.split("silently")[1]


def test_bg_preamble_default_config_unchanged():
    """Default config produces preamble with ping_user and report_updates."""
    config = BgForkConfig()

    result = _build_bg_preamble(0, 0, bg_config=config)

    assert "ping_user" in result
    assert "report_updates" in result
    assert "what happened" in result


# --- Preamble prompt quality ---


def test_bg_preamble_max_1_per_session():
    result = _build_bg_preamble(3, 5)

    assert "at most 1" in result


def test_bg_preamble_shows_remaining_tasks():
    result = _build_bg_preamble(2, 5)

    assert "2 bg reminders" in result
    assert "5 bg routines" in result
    assert "Still to fire today" in result


def test_bg_preamble_zero_budget_says_do_not_ping(data_dir):
    from datetime import date

    from ollim_bot import ping_budget

    ping_budget.save(
        ping_budget.BudgetState(
            daily_limit=10,
            used=10,
            critical_used=0,
            last_reset=date.today().isoformat(),
        )
    )

    result = _build_bg_preamble(0, 3)

    assert "do not attempt to ping" in result.lower()


# --- _fires_before_midnight ---


def test_fires_before_midnight_future_today(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )

    assert _fires_before_midnight("0 22 * * *") is True


def test_fires_before_midnight_already_passed(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=15, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )

    assert _fires_before_midnight("0 8 * * *") is False


def test_fires_before_midnight_wrong_dow(monkeypatch):
    now = datetime.now(TZ)
    # Pick a DOW that is NOT today (shift by 1)
    wrong_dow = str(((now.weekday() + 2) % 7))  # standard cron: 0=Sun
    fixed_now = now.replace(hour=6, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )

    assert _fires_before_midnight(f"0 22 * * {wrong_dow}") is False


# --- _remaining_bg_routine_firings ---


# --- Tool restriction preamble ---


def test_bg_preamble_allowed_tools():
    config = BgForkConfig(
        allowed_tools=["Bash(ollim-bot gmail *)", "Bash(ollim-bot tasks *)"]
    )

    result = _build_bg_preamble(0, 0, bg_config=config)

    assert "TOOL RESTRICTIONS" in result
    assert "Only these tools" in result
    assert "Bash(ollim-bot gmail *)" in result
    assert "Bash(ollim-bot tasks *)" in result


def test_bg_preamble_disallowed_tools():
    config = BgForkConfig(disallowed_tools=["WebFetch", "WebSearch"])

    result = _build_bg_preamble(0, 0, bg_config=config)

    assert "TOOL RESTRICTIONS" in result
    assert "NOT available" in result
    assert "WebFetch" in result
    assert "WebSearch" in result


def test_bg_preamble_no_tool_restrictions():
    config = BgForkConfig()

    result = _build_bg_preamble(0, 0, bg_config=config)

    assert "TOOL RESTRICTIONS" not in result


def test_reminder_prompt_bg_with_allowed_tools():
    reminder = Reminder(
        id="r1",
        message="Check email",
        run_at="2026-02-16T12:00:00-08:00",
        background=True,
        allowed_tools=["Bash(ollim-bot gmail *)"],
    )
    config = BgForkConfig(allowed_tools=reminder.allowed_tools)

    prompt = _build_reminder_prompt(
        reminder, reminders=[], routines=[], bg_config=config
    )

    assert "TOOL RESTRICTIONS" in prompt
    assert "Bash(ollim-bot gmail *)" in prompt


# --- _fires_before_midnight ---


# --- _build_upcoming_schedule ---


def _patch_now(monkeypatch, fixed_now):
    """Monkeypatch datetime.now() in scheduler module."""
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )


def test_schedule_includes_bg_routines(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        Routine(
            id="r1",
            message="Check tasks",
            cron="0 12 * * *",
            background=True,
            description="Midday task review",
        ),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) == 1
    assert entries[0].id == "r1"
    assert entries[0].description == "Midday task review"
    assert entries[0].tag is None  # neither [just fired] nor [this task]


def test_schedule_includes_bg_reminders(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    later = fixed_now + timedelta(hours=1)
    reminders = [
        Reminder(
            id="rem1",
            message="Check if Julius started the pipeline",
            run_at=later.isoformat(),
            background=True,
            description="ML pipeline check",
        ),
    ]

    entries = _build_upcoming_schedule([], reminders, current_id="other")

    assert len(entries) == 1
    assert entries[0].id == "rem1"


def test_schedule_excludes_foreground(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        Routine(id="fg", message="Foreground", cron="0 12 * * *", background=False),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) == 0


def test_schedule_marks_current_task(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        Routine(id="r1", message="Task A", cron="0 12 * * *", background=True),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="r1")

    assert entries[0].tag == "this task"


def test_schedule_marks_recently_fired(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=15, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        # Fires at 10:00, which is 15 min ago (within grace window)
        Routine(id="r1", message="Task A", cron="0 10 * * *", background=True),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) == 1
    assert entries[0].tag == "just fired"


def test_schedule_annotates_silent(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        Routine(
            id="r1",
            message="Silent",
            cron="0 12 * * *",
            background=True,
            allow_ping=False,
        ),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert entries[0].silent is True


def test_schedule_dynamic_extends_to_min_3(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        # Only 1 within 3h, but 3 total today
        Routine(id="r1", message="A", cron="0 12 * * *", background=True),
        Routine(id="r2", message="B", cron="0 16 * * *", background=True),
        Routine(id="r3", message="C", cron="0 20 * * *", background=True),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) >= 3  # extends beyond 3h to show at least 3


def test_schedule_uses_description_over_truncated_message(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        Routine(
            id="r1",
            message="A" * 200,
            cron="0 12 * * *",
            background=True,
            description="Short summary",
        ),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert entries[0].description == "Short summary"


def test_schedule_truncates_long_message_without_description(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    long_msg = "A" * 200
    routines = [
        Routine(id="r1", message=long_msg, cron="0 12 * * *", background=True),
    ]

    entries = _build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries[0].description) <= 63  # 60 chars + "..."
    assert entries[0].description.endswith("...")


def test_schedule_includes_chain_info(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    later = fixed_now + timedelta(hours=1)
    reminders = [
        Reminder(
            id="rem1",
            message="Check pipeline",
            run_at=later.isoformat(),
            background=True,
            chain_depth=1,
            max_chain=3,
        ),
    ]

    entries = _build_upcoming_schedule([], reminders, current_id="other")

    assert "2/4" in entries[0].label


# --- _remaining_bg_routine_firings (legacy, to be removed) ---


def test_remaining_bg_routine_firings_filters_correctly(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "ollim_bot.scheduling.scheduler.datetime",
        type(
            "dt",
            (datetime,),
            {"now": staticmethod(lambda tz=None: fixed_now)},
        ),
    )

    routines = [
        # fires at 22:00 today, bg, allow_ping — counted
        Routine(id="r1", message="a", cron="0 22 * * *", background=True),
        # fires at 8:00, already passed — not counted
        Routine(id="r2", message="b", cron="0 8 * * *", background=True),
        # foreground — not counted
        Routine(id="r3", message="c", cron="0 22 * * *", background=False),
        # allow_ping=False — not counted
        Routine(
            id="r4", message="d", cron="0 22 * * *", background=True, allow_ping=False
        ),
    ]

    assert _remaining_bg_routine_firings(routines) == 1
