"""Proactive reminders and check-ins via APScheduler.

All scheduled events route through the agent for contextual responses.
Reminders persist in ~/.ollim-bot/wakeups.jsonl and survive restarts.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ollim_bot.streamer import (
    _resolve_owner_id,
    run_agent_background,
    send_agent_dm,
)
from ollim_bot.wakeups import Wakeup, list_wakeups, remove_wakeup

TZ = ZoneInfo("America/Los_Angeles")


_registered: set[str] = set()


def _register_wakeup(
    scheduler: AsyncIOScheduler,
    bot: discord.Client,
    agent,
    wakeup: Wakeup,
):
    """Turn a Wakeup into a live APScheduler job."""
    if wakeup.id in _registered:
        return
    _registered.add(wakeup.id)

    if wakeup.background:
        prompt = (
            f"[background:{wakeup.id}] "
            "Your text output will be discarded. Use `ping_user` (MCP tool) to send "
            "a plain text alert, or `discord_embed` for structured data. Only alert "
            "if something genuinely warrants attention.\n\n"
            f"{wakeup.message}"
        )
    else:
        prompt = f"[reminder:{wakeup.id}] {wakeup.message}"

    async def _fire():
        uid = await _resolve_owner_id(bot)
        if wakeup.background:
            await run_agent_background(
                bot, agent, uid, prompt, skip_if_busy=wakeup.skip_if_busy
            )
        else:
            await send_agent_dm(bot, agent, uid, prompt)

    if wakeup.run_at:
        run_at = datetime.fromisoformat(wakeup.run_at)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=TZ)
        now = datetime.now(TZ)
        if run_at < now:
            run_at = now + timedelta(seconds=5)

        async def fire_oneshot():
            await _fire()
            remove_wakeup(wakeup.id)
            _registered.discard(wakeup.id)

        scheduler.add_job(
            fire_oneshot, DateTrigger(run_date=run_at), id=f"r_{wakeup.id}"
        )

    elif wakeup.cron:
        parts = wakeup.cron.split()
        scheduler.add_job(
            _fire,
            CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            ),
            id=f"r_{wakeup.id}",
        )

    elif wakeup.interval_minutes:
        scheduler.add_job(
            _fire,
            IntervalTrigger(minutes=wakeup.interval_minutes),
            id=f"r_{wakeup.id}",
        )


def setup_scheduler(bot: discord.Client, agent) -> AsyncIOScheduler:
    """Create scheduler and register reminders from wakeups.jsonl."""
    scheduler = AsyncIOScheduler(timezone="America/Los_Angeles")

    @scheduler.scheduled_job(IntervalTrigger(seconds=10))
    async def sync_reminders():
        current = list_wakeups()
        current_ids = {w.id for w in current}

        for wakeup in current:
            _register_wakeup(scheduler, bot, agent, wakeup)

        # Stop jobs for cancelled wakeups
        for stale_id in _registered - current_ids:
            job = scheduler.get_job(f"r_{stale_id}")
            if job:
                job.remove()
            _registered.discard(stale_id)

    return scheduler
