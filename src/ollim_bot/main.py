"""Entry point for ollim-bot."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import json
import logging
import os
import signal
import sys
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from dotenv import load_dotenv

if TYPE_CHECKING:
    from discord.ext.commands import Bot

from ollim_bot.storage import DATA_DIR, STATE_DIR

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
PID_FILE = STATE_DIR / "bot.pid"


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
  ollim-bot auth login       Log in to Claude (Agent SDK)
  ollim-bot auth status      Show auth status
  ollim-bot auth logout      Log out
  ollim-bot help             Show this help message

examples:
  ollim-bot routine add --cron "30 8 * * *" -m "Morning briefing"
  ollim-bot reminder add --delay 30 -m "take a break"
  ollim-bot tasks add "Fix login bug" --due 2026-02-15
  ollim-bot cal today
"""


def _ensure_sdk_layout() -> None:
    """Set up the SDK-expected directory structure in DATA_DIR.

    - Copies bundled agent specs to .claude/agents/ (with template expansion)
    - Symlinks .claude/skills/ -> ../skills/ for SDK skill discovery
    - Symlinks spec docs into DATA_DIR for agent access
    """
    from ollim_bot.subagents import install_agents

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Bundled agents → .claude/agents/
    install_agents()

    # Skills symlink → .claude/skills/ -> ../skills/
    skills_link = DATA_DIR / ".claude" / "skills"
    skills_link.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileExistsError):
        skills_link.symlink_to(Path("..") / "skills")

    # Spec doc symlinks
    for name in ("routine-reminder-spec.md", "webhook-spec.md"):
        source = PROJECT_DIR / "docs" / name
        target = DATA_DIR / name
        with contextlib.suppress(FileExistsError):
            target.symlink_to(source)


def _check_already_running() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        if proc_cmdline.exists() and "ollim-bot" in proc_cmdline.read_bytes().decode(errors="replace"):
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
    if cmd == "auth":
        from ollim_bot.auth import run_auth_command

        run_auth_command(rest)
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


log = logging.getLogger(__name__)


async def _notify_exit(bot: Bot, reason: str) -> None:
    """Best-effort DM to owner before the process exits."""
    from ollim_bot.bot import get_owner_id

    owner_id = get_owner_id()
    if not owner_id or bot.is_closed():
        return
    with contextlib.suppress(Exception):
        user = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
        dm = await user.create_dm()
        await dm.send(f"shutting down: {reason[:200]}")


async def _run(bot: Bot, token: str) -> None:
    """Run the bot, DM the owner on unexpected exits."""
    loop = asyncio.get_running_loop()
    _background_tasks: set[asyncio.Task[None]] = set()

    def _on_signal(sig_name: str) -> None:
        async def _shutdown() -> None:
            await _notify_exit(bot, f"received {sig_name}")
            if not bot.is_closed():
                await bot.close()

        task = loop.create_task(_shutdown())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    loop.add_signal_handler(signal.SIGTERM, _on_signal, "SIGTERM")
    loop.add_signal_handler(signal.SIGINT, _on_signal, "SIGINT")

    try:
        await bot.start(token)
    except asyncio.CancelledError:
        pass  # Signal handler already notified and closed
    except discord.LoginFailure:
        print("Invalid Discord token. Check DISCORD_TOKEN in .env", file=sys.stderr)
        print("Get a new token: Discord Developer Portal > Bot > Reset Token", file=sys.stderr)
        raise SystemExit(1) from None
    except discord.PrivilegedIntentsRequired:
        print("Message Content Intent is not enabled.", file=sys.stderr)
        print("Enable it: Discord Developer Portal > Bot > Privileged Gateway Intents", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as e:
        await _notify_exit(bot, f"{type(e).__name__}: {e}")
        raise
    finally:
        if not bot.is_closed():
            await bot.close()


def _discord_api(token: str, method: str, path: str, body: dict | None = None) -> dict:
    """Make a Discord REST API call."""
    url = f"https://discord.com/api/v10{path}"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _dm_owner(token: str, message: str) -> None:
    """Send a DM to the bot owner via Discord REST API."""
    app = _discord_api(token, "GET", "/oauth2/applications/@me")
    owner_id = app["owner"]["id"]
    channel = _discord_api(token, "POST", "/users/@me/channels", {"recipient_id": owner_id})
    _discord_api(token, "POST", f"/channels/{channel['id']}/messages", {"content": message})


def _login_via_discord(token: str) -> None:
    """Start Claude login and DM the auth URL to the bot owner."""
    from ollim_bot.auth import start_login

    print("Not logged in to Claude — starting login via Discord DM...")
    url, proc = start_login()
    _dm_owner(token, f"claude login required — click to authenticate:\n{url}")
    print("Login URL sent via Discord DM — waiting for authentication...")
    proc.wait()
    if proc.returncode != 0:
        print("Login failed — run `ollim-bot auth login` to try again")
        raise SystemExit(1)
    print("Login successful!")


def main() -> None:
    if _dispatch_subcommand():
        return

    load_dotenv(PROJECT_DIR / ".env")

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("Set DISCORD_TOKEN in .env")
        raise SystemExit(1)

    from ollim_bot.auth import is_authenticated

    if not is_authenticated():
        _login_via_discord(token)

    _check_already_running()
    _ensure_sdk_layout()

    from ollim_bot.bot import create_bot

    bot = create_bot()
    asyncio.run(_run(bot, token))


if __name__ == "__main__":
    main()
