"""Proactive routines and reminders via APScheduler.

Polls routines.jsonl and reminders.jsonl every 10s, registers APScheduler jobs.
Routines use CronTrigger, reminders use DateTrigger (one-shot, auto-removed).
Chain reminders inject chain context so the agent can call follow_up_chain.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ollim_bot.discord_tools import ChainContext, set_chain_context
from ollim_bot.reminders import Reminder, list_reminders, remove_reminder
from ollim_bot.routines import Routine, list_routines
from ollim_bot.streamer import _resolve_owner_id, run_agent_background, send_agent_dm

if TYPE_CHECKING:
    from ollim_bot.agent import Agent

TZ = ZoneInfo("America/Los_Angeles")

_BG_PREAMBLE = (
    "Your text output will be discarded. Use `ping_user` (MCP tool) to send "
    "a plain text alert, or `discord_embed` for structured data. Only alert "
    "if something genuinely warrants attention.\n\n"
)

_registered_routines: set[str] = set()
_registered_reminders: set[str] = set()

# Standard cron: 0=Sunday. APScheduler CronTrigger: 0=Monday.
# Convert numeric values to named days to avoid the mismatch.
_CRON_DOW = {
    "0": "sun",
    "1": "mon",
    "2": "tue",
    "3": "wed",
    "4": "thu",
    "5": "fri",
    "6": "sat",
    "7": "sun",
}


def _convert_dow(dow: str) -> str:
    """Convert standard cron day_of_week (0=Sun) to APScheduler names."""
    if dow == "*" or dow.startswith("*/"):
        return dow

    parts = dow.split(",")
    converted = []
    for part in parts:
        if "/" not in part and "-" not in part:
            converted.append(_CRON_DOW.get(part, part))
            continue
        if "/" in part:
            range_part, step = part.split("/", 1)
            if "-" in range_part:
                a, b = range_part.split("-", 1)
                converted.append(f"{_CRON_DOW.get(a, a)}-{_CRON_DOW.get(b, b)}/{step}")
            else:
                converted.append(f"{_CRON_DOW.get(range_part, range_part)}/{step}")
            continue
        a, b = part.split("-", 1)
        converted.append(f"{_CRON_DOW.get(a, a)}-{_CRON_DOW.get(b, b)}")
    return ",".join(converted)


def _build_routine_prompt(routine: Routine) -> str:
    if routine.background:
        return f"[routine-bg:{routine.id}] {_BG_PREAMBLE}{routine.message}"
    return f"[routine:{routine.id}] {routine.message}"


def _build_reminder_prompt(reminder: Reminder) -> str:
    tag = (
        f"reminder-bg:{reminder.id}"
        if reminder.background
        else f"reminder:{reminder.id}"
    )
    parts = [f"[{tag}]"]

    if reminder.background:
        parts.append(_BG_PREAMBLE.rstrip())

    if reminder.max_chain > 0:
        check_num = reminder.chain_depth + 1
        total = reminder.max_chain + 1
        if reminder.chain_depth < reminder.max_chain:
            parts.append(
                f"\nCHAIN CONTEXT: This is a follow-up chain reminder "
                f"(check {check_num} of {total}). You have `follow_up_chain` "
                f"available -- call follow_up_chain(minutes_from_now=N) to schedule "
                f"another check. If the task is done or no longer needs follow-up, "
                f"simply don't call it and the chain ends."
            )
        else:
            parts.append(
                f"\nCHAIN CONTEXT: This is the FINAL check in this follow-up chain "
                f"(check {check_num} of {total}). `follow_up_chain` is NOT available "
                f"-- this is your last chance to act on this reminder. If the task "
                f"needs attention, ping the user now."
            )

    parts.append(f"\n{reminder.message}")
    return "\n".join(parts)


def _register_routine(
    scheduler: AsyncIOScheduler, bot: discord.Client, agent: Agent, routine: Routine
) -> None:
    if routine.id in _registered_routines:
        return
    _registered_routines.add(routine.id)

    prompt = _build_routine_prompt(routine)

    async def _fire():
        uid = await _resolve_owner_id(bot)
        if routine.background:
            await run_agent_background(
                bot, agent, uid, prompt, skip_if_busy=routine.skip_if_busy
            )
        else:
            await send_agent_dm(bot, agent, uid, prompt)

    parts = routine.cron.split()
    scheduler.add_job(
        _fire,
        CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=_convert_dow(parts[4]),
        ),
        id=f"routine_{routine.id}",
    )


def _register_reminder(
    scheduler: AsyncIOScheduler, bot: discord.Client, agent: Agent, reminder: Reminder
) -> None:
    if reminder.id in _registered_reminders:
        return
    _registered_reminders.add(reminder.id)

    prompt = _build_reminder_prompt(reminder)

    async def fire_oneshot():
        uid = await _resolve_owner_id(bot)

        # follow_up_chain MCP tool reads this to schedule the next link
        if reminder.max_chain > 0 and reminder.chain_depth < reminder.max_chain:
            set_chain_context(
                ChainContext(
                    reminder_id=reminder.id,
                    message=reminder.message,
                    chain_depth=reminder.chain_depth,
                    max_chain=reminder.max_chain,
                    chain_parent=reminder.chain_parent or reminder.id,
                    background=reminder.background,
                )
            )

        if reminder.background:
            await run_agent_background(
                bot, agent, uid, prompt, skip_if_busy=reminder.skip_if_busy
            )
        else:
            await send_agent_dm(bot, agent, uid, prompt)

        set_chain_context(None)
        remove_reminder(reminder.id)
        _registered_reminders.discard(reminder.id)

    run_at = datetime.fromisoformat(reminder.run_at)
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=TZ)
    now = datetime.now(TZ)
    if run_at < now:
        run_at = now + timedelta(seconds=5)

    scheduler.add_job(
        fire_oneshot, DateTrigger(run_date=run_at), id=f"rem_{reminder.id}"
    )


def setup_scheduler(bot: discord.Client, agent: Agent) -> AsyncIOScheduler:
    """Polls routines/reminders every 10s, registering new and pruning stale jobs."""
    scheduler = AsyncIOScheduler(timezone="America/Los_Angeles")

    @scheduler.scheduled_job(IntervalTrigger(seconds=10))
    async def sync_all():
        current_routines = list_routines()
        current_routine_ids = {r.id for r in current_routines}
        for routine in current_routines:
            _register_routine(scheduler, bot, agent, routine)
        for stale_id in _registered_routines - current_routine_ids:
            job = scheduler.get_job(f"routine_{stale_id}")
            if job:
                job.remove()
            _registered_routines.discard(stale_id)

        current_reminders = list_reminders()
        current_reminder_ids = {r.id for r in current_reminders}
        for reminder in current_reminders:
            _register_reminder(scheduler, bot, agent, reminder)
        for stale_id in _registered_reminders - current_reminder_ids:
            job = scheduler.get_job(f"rem_{stale_id}")
            if job:
                job.remove()
            _registered_reminders.discard(stale_id)

    return scheduler
