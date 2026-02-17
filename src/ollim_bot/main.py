"""Entry point for ollim-bot."""

import asyncio
import atexit
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
PID_FILE = Path.home() / ".ollim-bot" / "bot.pid"


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
  ollim-bot cal today        Show today's calendar events
  ollim-bot cal upcoming     Show upcoming events
  ollim-bot cal add          Create a calendar event
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


def _check_already_running():
    """Exit if another ollim-bot process is already running."""
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


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("help", "--help", "-h"):
        print(HELP)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "routine":
        from ollim_bot.scheduling.routine_cmd import run_routine_command

        run_routine_command(sys.argv[2:])
        return

    if len(sys.argv) > 1 and sys.argv[1] == "reminder":
        from ollim_bot.scheduling.reminder_cmd import run_reminder_command

        run_reminder_command(sys.argv[2:])
        return

    if len(sys.argv) > 1 and sys.argv[1] == "tasks":
        from ollim_bot.google.tasks import run_tasks_command

        run_tasks_command(sys.argv[2:])
        return

    if len(sys.argv) > 1 and sys.argv[1] == "cal":
        from ollim_bot.google.calendar import run_calendar_command

        run_calendar_command(sys.argv[2:])
        return

    if len(sys.argv) > 1 and sys.argv[1] == "gmail":
        from ollim_bot.google.gmail import run_gmail_command

        run_gmail_command(sys.argv[2:])
        return

    load_dotenv(PROJECT_DIR / ".env")

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("Set DISCORD_TOKEN in .env")
        raise SystemExit(1)

    _check_already_running()

    from ollim_bot.bot import create_bot

    bot = create_bot()
    asyncio.run(bot.start(token))


if __name__ == "__main__":
    main()
