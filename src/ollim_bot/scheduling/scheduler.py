"""Proactive routines and reminders via APScheduler.

Polls routines/ and reminders/ markdown files every 10s, registers APScheduler jobs.
Routines use CronTrigger, reminders use DateTrigger (one-shot, auto-removed).
Chain reminders inject chain context so the agent can call follow_up_chain.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ollim_bot.agent_tools import (
    ChainContext,
    set_chain_context,
    set_fork_chain_context,
)
from ollim_bot.config import TZ, USER_NAME
from ollim_bot.embeds import fork_exit_embed
from ollim_bot.forks import (
    BgForkConfig,
    idle_timeout,
    in_interactive_fork,
    is_idle,
    run_agent_background,
    send_agent_dm,
    set_prompted_at,
    should_auto_exit,
    touch_activity,
)
from ollim_bot.scheduling.preamble import (
    _convert_dow,
    build_reminder_prompt,
    build_routine_prompt,
)
from ollim_bot.scheduling.reminders import Reminder, list_reminders, remove_reminder
from ollim_bot.scheduling.routines import Routine, list_routines
from ollim_bot.skills import Skill, collect_skill_tools, load_skills
from ollim_bot.streamer import stream_to_channel

if TYPE_CHECKING:
    from ollim_bot.agent import Agent

log = logging.getLogger(__name__)

_registered_routines: set[str] = set()
_registered_reminders: set[str] = set()

_PING_TOOLS = ["mcp__discord__ping_user", "mcp__discord__discord_embed"]


def _merge_skill_tools(config: BgForkConfig, skills: list[Skill]) -> BgForkConfig:
    """Merge tool dependencies from pre-loaded skills into the config.

    BgForkConfig.from_item always sets allowed_tools (MINIMAL_BG_TOOLS default),
    so config.allowed_tools is guaranteed non-None here.
    """
    skill_tools = collect_skill_tools(skills=skills)
    if not skill_tools:
        return config
    merged = list(config.allowed_tools or [])
    for tool in skill_tools:
        if tool not in merged:
            merged.append(tool)
    return replace(config, allowed_tools=merged)


def _apply_ping_restrictions(config: BgForkConfig) -> BgForkConfig:
    """Hide ping/embed tools from SDK when allow_ping is false.

    BgForkConfig.from_item always sets allowed_tools, so we filter directly.
    """
    if config.allow_ping:
        return config
    filtered = [t for t in (config.allowed_tools or []) if t not in _PING_TOOLS]
    return replace(config, allowed_tools=filtered)


def _register_routine(
    scheduler: AsyncIOScheduler,
    owner: discord.User,
    agent: Agent,
    routine: Routine,
) -> None:
    if routine.id in _registered_routines:
        return
    _registered_routines.add(routine.id)

    async def _fire() -> None:
        busy = agent.lock().locked()
        skills = load_skills(routine.skills)
        bg_config = BgForkConfig.from_item(routine)
        bg_config = _merge_skill_tools(bg_config, skills)
        bg_config = _apply_ping_restrictions(bg_config)
        # build_routine_prompt runs _expand_commands (sync subprocess, up to 30s)
        # — offload to thread to avoid blocking the event loop
        prompt = await asyncio.to_thread(
            build_routine_prompt,
            routine,
            reminders=list_reminders(),
            routines=list_routines(),
            busy=busy,
            bg_config=bg_config,
            skills=skills,
        )
        try:
            if routine.background:
                await run_agent_background(
                    agent,
                    prompt,
                    model=routine.model,
                    thinking=routine.thinking,
                    isolated=routine.isolated,
                    bg_config=bg_config,
                )
            else:
                if routine.model or routine.isolated:
                    log.warning(
                        "Routine %s: model/isolated only apply to background routines",
                        routine.id,
                    )
                await send_agent_dm(agent, prompt)
        except Exception:
            log.exception("Routine %s failed", routine.id)
            raise

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
    scheduler: AsyncIOScheduler,
    owner: discord.User,
    agent: Agent,
    reminder: Reminder,
) -> None:
    if reminder.id in _registered_reminders:
        return
    _registered_reminders.add(reminder.id)

    async def fire_oneshot() -> None:
        busy = agent.lock().locked()
        skills = load_skills(reminder.skills)
        bg_config = BgForkConfig.from_item(reminder)
        bg_config = _merge_skill_tools(bg_config, skills)
        bg_config = _apply_ping_restrictions(bg_config)
        # build_reminder_prompt runs _expand_commands (sync subprocess, up to 30s)
        # — offload to thread to avoid blocking the event loop
        prompt = await asyncio.to_thread(
            build_reminder_prompt,
            reminder,
            reminders=list_reminders(),
            routines=list_routines(),
            busy=busy,
            bg_config=bg_config,
            skills=skills,
        )
        # follow_up_chain MCP tool reads this to schedule the next link
        chain_ctx = None
        if reminder.max_chain > 0 and reminder.chain_depth < reminder.max_chain:
            chain_ctx = ChainContext(
                reminder_id=reminder.id,
                message=reminder.message,
                chain_depth=reminder.chain_depth,
                max_chain=reminder.max_chain,
                chain_parent=reminder.chain_parent or reminder.id,
                background=reminder.background,
                model=reminder.model,
                thinking=reminder.thinking,
                isolated=reminder.isolated,
                update_main_session=reminder.update_main_session,
                allow_ping=reminder.allow_ping,
                allowed_tools=reminder.allowed_tools,
                skills=reminder.skills,
            )

        try:
            if reminder.background:
                if chain_ctx:
                    set_fork_chain_context(chain_ctx)
                await run_agent_background(
                    agent,
                    prompt,
                    model=reminder.model,
                    thinking=reminder.thinking,
                    isolated=reminder.isolated,
                    bg_config=bg_config,
                )
            else:
                if reminder.model or reminder.isolated:
                    log.warning(
                        "Reminder %s: model/isolated only apply to background reminders",
                        reminder.id,
                    )
                if chain_ctx:
                    set_chain_context(chain_ctx)
                await send_agent_dm(agent, prompt)
        except Exception:
            log.exception("Reminder %s failed", reminder.id)
            raise
        finally:
            set_chain_context(None)
            remove_reminder(reminder.id)
            _registered_reminders.discard(reminder.id)

    run_at = datetime.fromisoformat(reminder.run_at)
    now = datetime.now(TZ)
    if run_at < now:
        run_at = now + timedelta(seconds=5)

    scheduler.add_job(fire_oneshot, DateTrigger(run_date=run_at), id=f"rem_{reminder.id}")


def setup_scheduler(bot: discord.Client, agent: Agent, owner: discord.User) -> AsyncIOScheduler:
    """Polls routines/reminders every 10s, registering new and pruning stale jobs."""
    scheduler = AsyncIOScheduler(timezone=str(TZ))

    @scheduler.scheduled_job(IntervalTrigger(seconds=10))
    async def sync_all() -> None:
        current_routines = list_routines()
        current_routine_ids = {r.id for r in current_routines}
        for routine in current_routines:
            _register_routine(scheduler, owner, agent, routine)
        for stale_id in _registered_routines - current_routine_ids:
            job = scheduler.get_job(f"routine_{stale_id}")
            if job:
                job.remove()
            _registered_routines.discard(stale_id)

        current_reminders = list_reminders()
        current_reminder_ids = {r.id for r in current_reminders}
        for reminder in current_reminders:
            _register_reminder(scheduler, owner, agent, reminder)
        for stale_id in _registered_reminders - current_reminder_ids:
            job = scheduler.get_job(f"rem_{stale_id}")
            if job:
                job.remove()
            _registered_reminders.discard(stale_id)

    # max_instances=2 prevents APScheduler from refusing to schedule a second
    # invocation (which logs a warning). _fork_check_busy is the real guard:
    # if a check is already running, the new invocation returns immediately.
    _fork_check_busy = False

    @scheduler.scheduled_job(IntervalTrigger(seconds=60), max_instances=2)
    async def check_fork_timeout() -> None:
        nonlocal _fork_check_busy
        if _fork_check_busy or not in_interactive_fork():
            return
        _fork_check_busy = True
        try:
            await _do_fork_check()
        finally:
            _fork_check_busy = False

    async def _do_fork_check() -> None:
        if not is_idle():
            return

        escalated = should_auto_exit()
        if not escalated:
            set_prompted_at()
        dm = await owner.create_dm()
        timeout = idle_timeout()

        if escalated:
            prompt = (
                f"[fork-timeout] This fork has been idle for {timeout * 2} minutes "
                "and you already received a timeout notice. You MUST exit now."
            )
        else:
            prompt = (
                f"[fork-timeout] This fork has been idle for {timeout} minutes. "
                f"If {USER_NAME} is still engaged, ask them. Otherwise, exit the fork."
            )

        async with agent.lock():
            await dm.typing()
            await stream_to_channel(dm, agent.stream_chat(prompt))
            result = await agent.pop_fork_exit()
            if result:
                action, summary = result
                await dm.send(embed=fork_exit_embed(action, summary))
            else:
                touch_activity()

    return scheduler
