"""Entry point for ollim-bot."""

import asyncio
import atexit
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path.home() / ".ollim-bot"
PID_FILE = DATA_DIR / "bot.pid"


HELP = """\
ollim-bot -- ADHD-friendly Discord assistant powered by Claude

commands:
  ollim-bot                  Run the Discord bot
  ollim-bot routine add      Add a recurring routine (cron)
  ollim-bot routine list     Show all routines
  ollim-bot routine cancel   Cancel a routine by ID
  ollim-bot reminder add     Schedule a one-shot reminder
  ollim-bot reminder list    Show pending reminders
  ollim-bot reminder cancel  Cancel a reminder by ID
  ollim-bot tasks list       List Google Tasks
  ollim-bot tasks add        Add a task
  ollim-bot tasks done       Mark task as completed
  ollim-bot tasks update     Update a task
  ollim-bot tasks delete     Delete a task
  ollim-bot cal today        Show today's calendar events
  ollim-bot cal upcoming     Show upcoming events
  ollim-bot cal show         Show event details
  ollim-bot cal add          Create a calendar event
  ollim-bot cal update       Update a calendar event
  ollim-bot cal delete       Delete a calendar event
  ollim-bot gmail unread     List unread emails
  ollim-bot gmail read       Read an email by ID
  ollim-bot gmail search     Search emails
  ollim-bot help             Show this help message

examples:
  ollim-bot routine add --cron "30 8 * * *" -m "Morning briefing"
  ollim-bot reminder add --delay 30 -m "take a break"
  ollim-bot tasks add "Fix login bug" --due 2026-02-15
  ollim-bot cal today
"""


def _ensure_spec_symlinks() -> None:
    """Symlink spec docs into the data dir for agent access."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("routine-reminder-spec.md", "webhook-spec.md"):
        source = PROJECT_DIR / "docs" / name
        target = DATA_DIR / name
        if target.is_symlink() or target.exists():
            continue
        target.symlink_to(source)


def _check_already_running() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        if proc_cmdline.exists() and "ollim-bot" in proc_cmdline.read_bytes().decode(
            errors="replace"
        ):
            print(f"ollim-bot is already running (pid {pid})")
            raise SystemExit(1)
    PID_FILE.write_text(str(os.getpid()))
    atexit.register(PID_FILE.unlink, missing_ok=True)


def _dispatch_subcommand() -> bool:
    """Route CLI subcommands. Returns True if handled."""
    if len(sys.argv) < 2:
        return False
    cmd = sys.argv[1]
    rest = sys.argv[2:]
    if cmd in ("help", "--help", "-h"):
        print(HELP)
        return True
    routes: dict[str, tuple[str, str]] = {
        "routine": ("ollim_bot.scheduling.routine_cmd", "run_routine_command"),
        "reminder": ("ollim_bot.scheduling.reminder_cmd", "run_reminder_command"),
        "tasks": ("ollim_bot.google.tasks", "run_tasks_command"),
        "cal": ("ollim_bot.google.calendar", "run_calendar_command"),
        "gmail": ("ollim_bot.google.gmail", "run_gmail_command"),
    }
    if cmd in routes:
        from importlib import import_module

        mod_path, func_name = routes[cmd]
        getattr(import_module(mod_path), func_name)(rest)
        return True
    return False


def main() -> None:
    if _dispatch_subcommand():
        return

    load_dotenv(PROJECT_DIR / ".env")

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("Set DISCORD_TOKEN in .env")
        raise SystemExit(1)

    _check_already_running()
    _ensure_spec_symlinks()

    from ollim_bot.bot import create_bot

    bot = create_bot()
    asyncio.run(bot.start(token))


if __name__ == "__main__":
    main()
