"""Tests for scheduler.py prompt-building and cron conversion."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ollim_bot.forks import BgForkConfig
from ollim_bot.scheduling.preamble import (
    ScheduleEntry,
    _convert_dow,
    build_bg_preamble,
    build_reminder_prompt,
    build_routine_prompt,
    build_upcoming_schedule,
)
from ollim_bot.scheduling.reminders import Reminder
from ollim_bot.scheduling.routines import Routine

TZ = ZoneInfo("America/Los_Angeles")


def test_routine_prompt_foreground():
    routine = Routine(id="abc", message="Morning briefing", cron="0 8 * * *")

    prompt = build_routine_prompt(routine, reminders=[], routines=[])

    assert prompt == "[routine:abc] Morning briefing"


def test_routine_prompt_background():
    routine = Routine(id="def", message="Silent check", cron="0 8 * * *", background=True)

    prompt = build_routine_prompt(routine, reminders=[], routines=[])

    assert prompt.startswith("[routine-bg:def]")
    assert "ping_user" in prompt
    assert "Silent check" in prompt


def test_reminder_prompt_plain():
    reminder = Reminder(id="r1", message="Take a break", run_at="2026-02-16T12:00:00-08:00")

    prompt = build_reminder_prompt(reminder, reminders=[], routines=[])

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

    prompt = build_reminder_prompt(reminder, reminders=[], routines=[])

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

    prompt = build_reminder_prompt(reminder, reminders=[], routines=[])

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

    prompt = build_reminder_prompt(reminder, reminders=[], routines=[])

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

    prompt = build_reminder_prompt(reminder, reminders=[], routines=[])

    assert "check 1 of 3" in prompt
    assert "follow_up_chain" in prompt


def test_bg_routine_prompt_includes_budget(data_dir):
    routine = Routine(id="abc", message="Check tasks", cron="0 8 * * *", background=True)

    prompt = build_routine_prompt(routine, reminders=[], routines=[routine])

    assert "available" in prompt
    assert "Ping budget" in prompt


def test_bg_reminder_prompt_includes_budget(data_dir):
    reminder = Reminder(
        id="r1",
        message="Check email",
        run_at="2026-02-16T12:00:00-08:00",
        background=True,
    )

    prompt = build_reminder_prompt(reminder, reminders=[reminder], routines=[])

    assert "available" in prompt
    assert "Ping budget" in prompt


def test_fg_routine_prompt_unchanged(data_dir):
    routine = Routine(id="abc", message="Morning briefing", cron="0 8 * * *")

    prompt = build_routine_prompt(routine, reminders=[], routines=[])

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
    result = build_bg_preamble([])
    assert "mid-conversation" not in result
    assert "report_updates" in result


def test_bg_preamble_busy_includes_quiet_instruction():
    result = build_bg_preamble([], busy=True)
    assert "mid-conversation" in result
    assert "report_updates" in result
    assert "critical" in result.lower()


def test_bg_routine_prompt_busy(data_dir):
    routine = Routine(id="abc", message="Check tasks", cron="0 8 * * *", background=True)

    prompt = build_routine_prompt(routine, reminders=[], routines=[], busy=True)

    assert "mid-conversation" in prompt
    assert "Check tasks" in prompt


def test_bg_reminder_prompt_busy(data_dir):
    reminder = Reminder(
        id="r1",
        message="Check email",
        run_at="2026-02-16T12:00:00-08:00",
        background=True,
    )

    prompt = build_reminder_prompt(reminder, reminders=[], routines=[], busy=True)

    assert "mid-conversation" in prompt
    assert "Check email" in prompt


# --- BgForkConfig-aware preamble ---


def test_bg_preamble_allow_ping_false():
    config = BgForkConfig(allow_ping=False)

    result = build_bg_preamble([], bg_config=config)

    assert "disabled" in result.lower()
    assert "not available" in result.lower()
    assert "Ping budget" not in result


def test_bg_preamble_update_always():
    config = BgForkConfig(update_main_session="always")

    result = build_bg_preamble([], bg_config=config)

    assert "MUST" in result
    assert "report_updates" in result


def test_bg_preamble_update_freely():
    config = BgForkConfig(update_main_session="freely")

    result = build_bg_preamble([], bg_config=config)

    assert "optionally" in result.lower()
    assert "report_updates" in result


def test_bg_preamble_update_blocked():
    config = BgForkConfig(update_main_session="blocked")

    result = build_bg_preamble([], bg_config=config)

    assert "silently" in result.lower()
    assert "report_updates" not in result.split("silently")[1]


def test_bg_preamble_default_config_unchanged():
    """Default config produces preamble with ping_user and report_updates."""
    config = BgForkConfig()

    result = build_bg_preamble([], bg_config=config)

    assert "ping_user" in result
    assert "report_updates" in result
    assert "what happened" in result


# --- Preamble prompt quality ---


def test_bg_preamble_max_1_per_session():
    result = build_bg_preamble([])

    assert "at most 1" in result


def test_bg_preamble_shows_schedule(data_dir):
    now = datetime.now(TZ)
    entries = [
        ScheduleEntry(
            id="r1",
            fire_time=now + timedelta(hours=1),
            label="Midday review",
            description="Check tasks",
            file_path="routines/r1.md",
        ),
    ]

    result = build_bg_preamble(entries)

    assert "Upcoming bg tasks" in result
    assert "Check tasks" in result
    assert "routines/r1.md" in result


def test_bg_preamble_no_schedule_says_no_more(data_dir):
    result = build_bg_preamble([])

    assert "No more bg tasks today" in result


# --- _fires_before_midnight ---


# --- Tool restriction preamble ---


def test_bg_preamble_allowed_tools():
    config = BgForkConfig(allowed_tools=["Bash(ollim-bot gmail *)", "Bash(ollim-bot tasks *)"])

    result = build_bg_preamble([], bg_config=config)

    assert "TOOL RESTRICTIONS" in result
    assert "Only these tools" in result
    assert "Bash(ollim-bot gmail *)" in result
    assert "Bash(ollim-bot tasks *)" in result


def test_bg_preamble_disallowed_tools():
    config = BgForkConfig(disallowed_tools=["WebFetch", "WebSearch"])

    result = build_bg_preamble([], bg_config=config)

    assert "TOOL RESTRICTIONS" in result
    assert "NOT available" in result
    assert "WebFetch" in result
    assert "WebSearch" in result


def test_bg_preamble_no_tool_restrictions():
    config = BgForkConfig()

    result = build_bg_preamble([], bg_config=config)

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

    prompt = build_reminder_prompt(reminder, reminders=[], routines=[], bg_config=config)

    assert "TOOL RESTRICTIONS" in prompt
    assert "Bash(ollim-bot gmail *)" in prompt


# --- build_upcoming_schedule ---


def _patch_now(monkeypatch, fixed_now):
    """Monkeypatch datetime.now() in preamble module."""
    monkeypatch.setattr(
        "ollim_bot.scheduling.preamble.datetime",
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

    entries = build_upcoming_schedule(routines, [], current_id="other")

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

    entries = build_upcoming_schedule([], reminders, current_id="other")

    assert len(entries) == 1
    assert entries[0].id == "rem1"


def test_schedule_excludes_foreground(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        Routine(id="fg", message="Foreground", cron="0 12 * * *", background=False),
    ]

    entries = build_upcoming_schedule(routines, [], current_id="other")

    assert len(entries) == 0


def test_schedule_marks_current_task(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        Routine(id="r1", message="Task A", cron="0 12 * * *", background=True),
    ]

    entries = build_upcoming_schedule(routines, [], current_id="r1")

    assert entries[0].tag == "this task"


def test_schedule_marks_recently_fired(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=15, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    routines = [
        # Fires at 10:00, which is 15 min ago (within grace window)
        Routine(id="r1", message="Task A", cron="0 10 * * *", background=True),
    ]

    entries = build_upcoming_schedule(routines, [], current_id="other")

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

    entries = build_upcoming_schedule(routines, [], current_id="other")

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

    entries = build_upcoming_schedule(routines, [], current_id="other")

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

    entries = build_upcoming_schedule(routines, [], current_id="other")

    assert entries[0].description == "Short summary"


def test_schedule_truncates_long_message_without_description(monkeypatch):
    fixed_now = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    _patch_now(monkeypatch, fixed_now)
    long_msg = "A" * 200
    routines = [
        Routine(id="r1", message=long_msg, cron="0 12 * * *", background=True),
    ]

    entries = build_upcoming_schedule(routines, [], current_id="other")

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

    entries = build_upcoming_schedule([], reminders, current_id="other")

    assert "2/4" in entries[0].label
