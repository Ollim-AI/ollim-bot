"""Entry point for ollim-bot."""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
PID_FILE = Path.home() / ".ollim-bot" / "bot.pid"


HELP = """\
ollim-bot -- ADHD-friendly Discord assistant powered by Claude

commands:
  ollim-bot                 Run the Discord bot
  ollim-bot schedule add    Schedule a wakeup/reminder
  ollim-bot schedule list   Show pending wakeups
  ollim-bot schedule cancel Cancel a wakeup by ID
  ollim-bot help            Show this help message

examples:
  ollim-bot schedule add --delay 30 -m "take a break"
  ollim-bot schedule add --cron "0 9 * * 1-5" -m "morning standup"
  ollim-bot schedule add --every 120 -m "focus check"
  ollim-bot schedule cancel abc123
"""


def _check_already_running():
    """Exit if another ollim-bot process is already running."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        if proc_cmdline.exists() and "ollim-bot" in proc_cmdline.read_bytes().decode(errors="replace"):
            print(f"ollim-bot is already running (pid {pid})")
            raise SystemExit(1)
    PID_FILE.write_text(str(os.getpid()))


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("help", "--help", "-h"):
        print(HELP)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "schedule":
        from ollim_bot.schedule_cmd import run_schedule_command

        run_schedule_command(sys.argv[2:])
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
