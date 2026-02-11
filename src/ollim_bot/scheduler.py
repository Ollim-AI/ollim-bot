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

from ollim_bot.wakeups import Wakeup, list_wakeups, remove_wakeup

TZ = ZoneInfo("America/Los_Angeles")


_owner_id: str | None = None
_registered: set[str] = set()


async def _resolve_owner_id(bot: discord.Client) -> str:
    global _owner_id
    if _owner_id is None:
        app_info = await bot.application_info()
        _owner_id = str(app_info.owner.id) if app_info.owner else "unknown"
    return _owner_id


async def _send_agent_dm(bot: discord.Client, agent, user_id: str, prompt: str):
    """Inject a prompt into the agent session and DM the response."""
    response = await agent.chat(prompt, user_id)
    app_info = await bot.application_info()
    owner = app_info.owner
    if not owner:
        return
    dm = await owner.create_dm()
    for i in range(0, len(response), 2000):
        await dm.send(response[i : i + 2000])


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

    prompt = f"[reminder:{wakeup.id}] {wakeup.message}"

    if wakeup.run_at:
        run_at = datetime.fromisoformat(wakeup.run_at)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=TZ)
        now = datetime.now(TZ)
        if run_at < now:
            run_at = now + timedelta(seconds=5)

        async def fire_oneshot():
            uid = await _resolve_owner_id(bot)
            await _send_agent_dm(bot, agent, uid, prompt)
            remove_wakeup(wakeup.id)
            _registered.discard(wakeup.id)

        scheduler.add_job(fire_oneshot, DateTrigger(run_date=run_at), id=f"r_{wakeup.id}")

    elif wakeup.cron:
        parts = wakeup.cron.split()

        async def fire_cron():
            uid = await _resolve_owner_id(bot)
            await _send_agent_dm(bot, agent, uid, prompt)

        scheduler.add_job(
            fire_cron,
            CronTrigger(
                minute=parts[0], hour=parts[1], day=parts[2],
                month=parts[3], day_of_week=parts[4],
            ),
            id=f"r_{wakeup.id}",
        )

    elif wakeup.interval_minutes:
        async def fire_interval():
            uid = await _resolve_owner_id(bot)
            await _send_agent_dm(bot, agent, uid, prompt)

        scheduler.add_job(
            fire_interval,
            IntervalTrigger(minutes=wakeup.interval_minutes),
            id=f"r_{wakeup.id}",
        )


def setup_scheduler(bot: discord.Client, agent) -> AsyncIOScheduler:
    """Create scheduler with agent-powered static jobs + reminder sync."""
    scheduler = AsyncIOScheduler(timezone="America/Los_Angeles")

    # -- Morning standup (9 AM PT) --
    @scheduler.scheduled_job(CronTrigger(hour=9, minute=0))
    async def morning_standup():
        uid = await _resolve_owner_id(bot)
        await _send_agent_dm(
            bot, agent, uid,
            "[reminder:morning] Good morning! What are your top 3 priorities today?",
        )

    # -- Evening review (6 PM PT) --
    @scheduler.scheduled_job(CronTrigger(hour=18, minute=0))
    async def evening_review():
        uid = await _resolve_owner_id(bot)
        await _send_agent_dm(
            bot, agent, uid,
            "[reminder:evening] Wrapping up. What did you get done today? What carries over?",
        )

    # -- Focus check-in (every 90 min during work hours) --
    @scheduler.scheduled_job(IntervalTrigger(minutes=90))
    async def focus_checkin():
        hour = datetime.now(TZ).hour
        if 9 <= hour < 18:
            uid = await _resolve_owner_id(bot)
            await _send_agent_dm(
                bot, agent, uid,
                "[reminder:focus] Quick check-in: still on the same task, or did something pull you away?",
            )

    # -- Sync reminders from file (every 10s) --
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
