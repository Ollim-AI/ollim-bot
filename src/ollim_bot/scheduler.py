"""Proactive reminders and check-ins via APScheduler.

All scheduled events route through the agent for contextual responses.
Dynamic wakeups are polled from ~/.ollim-bot/wakeups.jsonl.
"""

from datetime import datetime, timedelta

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ollim_bot.wakeups import Wakeup, drain_wakeups


_owner_id: str | None = None


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
    prompt = f"[wakeup:{wakeup.id}] {wakeup.message}"

    async def fire():
        uid = await _resolve_owner_id(bot)
        await _send_agent_dm(bot, agent, uid, prompt)

    if wakeup.delay_minutes:
        trigger = DateTrigger(
            run_date=datetime.now() + timedelta(minutes=wakeup.delay_minutes)
        )
    elif wakeup.cron:
        parts = wakeup.cron.split()
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    elif wakeup.interval_minutes:
        trigger = IntervalTrigger(minutes=wakeup.interval_minutes)
    else:
        return

    scheduler.add_job(fire, trigger, id=f"wakeup_{wakeup.id}")


def setup_scheduler(bot: discord.Client, agent) -> AsyncIOScheduler:
    """Create scheduler with agent-powered static jobs + wakeup polling."""
    scheduler = AsyncIOScheduler(timezone="America/Los_Angeles")

    # -- Morning standup (9 AM PT) --
    @scheduler.scheduled_job(CronTrigger(hour=9, minute=0))
    async def morning_standup():
        uid = await _resolve_owner_id(bot)
        await _send_agent_dm(
            bot, agent, uid,
            "[wakeup:morning] Good morning! What are your top 3 priorities today?",
        )

    # -- Evening review (6 PM PT) --
    @scheduler.scheduled_job(CronTrigger(hour=18, minute=0))
    async def evening_review():
        uid = await _resolve_owner_id(bot)
        await _send_agent_dm(
            bot, agent, uid,
            "[wakeup:evening] Wrapping up. What did you get done today? What carries over?",
        )

    # -- Focus check-in (every 90 min during work hours) --
    @scheduler.scheduled_job(
        IntervalTrigger(minutes=90),
        next_run_time=None,
    )
    async def focus_checkin():
        hour = datetime.now().hour
        if 9 <= hour < 18:
            uid = await _resolve_owner_id(bot)
            await _send_agent_dm(
                bot, agent, uid,
                "[wakeup:focus] Quick check-in: still on the same task, or did something pull you away?",
            )

    # -- Drain wakeup queue (every 10s) --
    @scheduler.scheduled_job(IntervalTrigger(seconds=10))
    async def drain_wakeup_queue():
        for wakeup in drain_wakeups():
            _register_wakeup(scheduler, bot, agent, wakeup)

    return scheduler
