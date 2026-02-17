"""Tests for routine_cmd.py and reminder_cmd.py CLI handlers."""

import io
import sys

from ollim_bot.scheduling.reminder_cmd import run_reminder_command
from ollim_bot.scheduling.routine_cmd import run_routine_command


def _capture_stdout(fn, *args):
    old = sys.stdout
    sys.stdout = buf = io.StringIO()
    fn(*args)
    sys.stdout = old
    return buf.getvalue()


def test_routine_add_and_list(data_dir):
    output = _capture_stdout(
        run_routine_command, ["add", "--cron", "0 9 * * *", "-m", "morning check"]
    )
    assert "scheduled" in output
    assert "morning check" in output

    output = _capture_stdout(run_routine_command, ["list"])
    assert "morning check" in output
    assert "0 9 * * *" in output


def test_routine_cancel(data_dir):
    output = _capture_stdout(
        run_routine_command, ["add", "--cron", "0 9 * * *", "-m", "to cancel"]
    )
    routine_id = output.split()[1].rstrip(":")

    output = _capture_stdout(run_routine_command, ["cancel", routine_id])
    assert "cancelled" in output

    output = _capture_stdout(run_routine_command, ["list"])
    assert "no routines" in output


def test_routine_add_background(data_dir):
    output = _capture_stdout(
        run_routine_command,
        ["add", "--cron", "*/5 * * * *", "-m", "bg task", "--background"],
    )
    assert "scheduled" in output

    output = _capture_stdout(run_routine_command, ["list"])
    assert "[bg]" in output


def test_reminder_add_and_list(data_dir):
    output = _capture_stdout(
        run_reminder_command, ["add", "--delay", "30", "-m", "take a break"]
    )
    assert "scheduled" in output
    assert "take a break" in output

    output = _capture_stdout(run_reminder_command, ["list"])
    assert "take a break" in output


def test_reminder_cancel(data_dir):
    output = _capture_stdout(
        run_reminder_command, ["add", "--delay", "10", "-m", "to cancel"]
    )
    reminder_id = output.split()[1].rstrip(":")

    output = _capture_stdout(run_reminder_command, ["cancel", reminder_id])
    assert "cancelled" in output

    output = _capture_stdout(run_reminder_command, ["list"])
    assert "no pending reminders" in output


def test_reminder_add_with_chain(data_dir):
    output = _capture_stdout(
        run_reminder_command,
        ["add", "--delay", "60", "-m", "chain test", "--max-chain", "3"],
    )
    assert "scheduled" in output

    output = _capture_stdout(run_reminder_command, ["list"])
    assert "chain 0/3" in output


def test_reminder_add_background(data_dir):
    output = _capture_stdout(
        run_reminder_command,
        ["add", "--delay", "15", "-m", "bg reminder", "--background"],
    )
    assert "scheduled" in output

    output = _capture_stdout(run_reminder_command, ["list"])
    assert "[bg]" in output
