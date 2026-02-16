"""Tests for scheduler.py prompt-building functions."""

from ollim_bot.reminders import Reminder
from ollim_bot.routines import Routine
from ollim_bot.scheduler import _build_reminder_prompt, _build_routine_prompt


def test_routine_prompt_foreground():
    routine = Routine(id="abc", message="Morning briefing", cron="0 8 * * *")

    prompt = _build_routine_prompt(routine)

    assert prompt == "[routine:abc] Morning briefing"


def test_routine_prompt_background():
    routine = Routine(
        id="def", message="Silent check", cron="0 8 * * *", background=True
    )

    prompt = _build_routine_prompt(routine)

    assert prompt.startswith("[routine-bg:def]")
    assert "ping_user" in prompt
    assert "Silent check" in prompt


def test_reminder_prompt_plain():
    reminder = Reminder(
        id="r1", message="Take a break", run_at="2026-02-16T12:00:00-08:00"
    )

    prompt = _build_reminder_prompt(reminder)

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

    prompt = _build_reminder_prompt(reminder)

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

    prompt = _build_reminder_prompt(reminder)

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

    prompt = _build_reminder_prompt(reminder)

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

    prompt = _build_reminder_prompt(reminder)

    assert "check 1 of 3" in prompt
    assert "follow_up_chain" in prompt
