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

from ollim_bot.discord_tools import set_channel
from ollim_bot.streamer import stream_to_channel
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
    """Inject a prompt into the agent session and stream the response as a DM."""
    app_info = await bot.application_info()
    owner = app_info.owner
    if not owner:
        return
    dm = await owner.create_dm()
    async with agent.lock(user_id):
        set_channel(dm)
        await dm.typing()
        await stream_to_channel(dm, agent.stream_chat(prompt, user_id))


async def _run_background(
    bot: discord.Client, agent, user_id: str, prompt: str, *, skip_if_busy: bool
):
    """Run agent silently -- output discarded, tools (ping_user/discord_embed) break through."""
    app_info = await bot.application_info()
    owner = app_info.owner
    if not owner:
        return
    dm = await owner.create_dm()

    if skip_if_busy and agent.lock(user_id).locked():
        return

    async with agent.lock(user_id):
        set_channel(dm)
        async for _ in agent.stream_chat(prompt, user_id):
            pass  # discard text -- agent uses tools to alert


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
            await _run_background(
                bot, agent, uid, prompt, skip_if_busy=wakeup.skip_if_busy
            )
        else:
            await _send_agent_dm(bot, agent, uid, prompt)

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
