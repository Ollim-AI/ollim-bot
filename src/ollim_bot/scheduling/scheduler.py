# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Proactive routines and reminders via APScheduler.

Polls routines/ and reminders/ markdown files every 10s, registers APScheduler jobs.
Routines use CronTrigger, reminders use DateTrigger (one-shot, auto-removed).
Chain reminders inject chain context so the agent can call follow_up_chain.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import discord
import yaml
from apscheduler.events import EVENT_JOB_MISSED, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ollim_bot.agent_context import thinking_mode
from ollim_bot.agent_tools import (
    ChainContext,
    set_chain_context,
    set_fork_chain_context,
)
from ollim_bot.channel import get_channel
from ollim_bot.config import TZ, USER_NAME
from ollim_bot.embeds import fork_exit_embed
from ollim_bot.fork_state import (
    BgForkConfig,
    idle_timeout,
    in_interactive_fork,
    is_idle,
    set_prompted_at,
    should_auto_exit,
    touch_activity,
)
from ollim_bot.forks import (
    append_update,
    run_agent_background,
    send_agent_dm,
)
from ollim_bot.google.auth import check_and_clear_revoked
from ollim_bot.scheduling.preamble import (
    _convert_dow,
    build_reminder_prompt,
    build_routine_prompt,
)
from ollim_bot.scheduling.reminders import REMINDERS_DIR, Reminder, list_reminders, remove_reminder
from ollim_bot.scheduling.routines import ROUTINES_DIR, Routine, list_routines
from ollim_bot.sessions import (
    cancel_message_collector,
    flush_message_collector,
    load_session_id,
    start_message_collector,
)
from ollim_bot.skills import cleanup_stale_skills, ensure_skill
from ollim_bot.streamer import stream_to_channel

if TYPE_CHECKING:
    from ollim_bot.agent import Agent
    from ollim_bot.runtime_config import RuntimeConfig

log = logging.getLogger(__name__)

_registered_routines: set[str] = set()
_registered_reminders: set[str] = set()
_reported_problems: set[str] = set()


def _check_corrupt_files(
    loaded_count: int,
    kind: Literal["routine", "reminder"],
    all_files: list[Path],
) -> None:
    """Surface corrupt routine/reminder files to the agent via pending_updates."""
    skipped = len(all_files) - loaded_count
    problem_key = f"corrupt_{kind}_files"

    if skipped > 0:
        if problem_key not in _reported_problems:
            _reported_problems.add(problem_key)
            from ollim_bot.storage import parse_md

            cls = Routine if kind == "routine" else Reminder
            names = []
            for filepath in all_files:
                try:
                    parse_md(filepath.read_text(encoding="utf-8"), cls)
                except (ValueError, yaml.YAMLError, TypeError, KeyError):
                    names.append(filepath.name)
            file_list = ", ".join(names) if names else f"{skipped} file(s)"
            asyncio.get_event_loop().create_task(
                append_update(
                    f"**{skipped} corrupt {kind} file(s)** skipped by scheduler: {file_list} — "
                    f"read and fix them, or delete and recreate"
                )
            )
    elif problem_key in _reported_problems:
        _reported_problems.discard(problem_key)


def _merge_skill_tools(config: BgForkConfig, skill_names: list[str] | None) -> BgForkConfig:
    """Add Skill(<name> *) patterns to allowed_tools for background fork dispatch."""
    if not skill_names:
        return config
    additions = [f"Skill({name} *)" for name in skill_names]
    current = set(config.allowed_tools or [])
    new = [t for t in additions if t not in current]
    if not new:
        return config
    return replace(config, allowed_tools=list(current) + new)


def _register_routine(
    scheduler: AsyncIOScheduler,
    owner: discord.User,
    agent: Agent,
    routine: Routine,
) -> None:
    if routine.id in _registered_routines:
        return

    async def _fire() -> None:
        busy = agent.lock().locked()
        bg_config: BgForkConfig | None = None
        reminders: list[Reminder] = []
        routines: list[Routine] = []
        if routine.background:
            from ollim_bot.tool_policy import validate_dispatch

            bg_config = BgForkConfig.from_item(routine)
            bg_config = _merge_skill_tools(bg_config, routine.skills)
            if not validate_dispatch(bg_config.allowed_tools, source=routine.id):
                return
            reminders = list_reminders()
            routines = list_routines()
        sname = ensure_skill(routine)
        prompt = build_routine_prompt(
            routine,
            skill_name=sname,
            reminders=reminders,
            routines=routines,
            busy=busy,
            bg_config=bg_config,
        )
        try:
            if routine.background:
                await run_agent_background(
                    agent,
                    prompt,
                    model=routine.model,
                    thinking=thinking_mode(routine.thinking),
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
    try:
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
    except (ValueError, KeyError, IndexError):
        log.exception("Failed to register routine %s (cron: %s)", routine.id, routine.cron)
        problem_key = f"routine_reg_{routine.id}"
        if problem_key not in _reported_problems:
            _reported_problems.add(problem_key)
            asyncio.get_event_loop().create_task(
                append_update(f"Routine **{routine.id}** failed to register — invalid cron `{routine.cron}`")
            )
        return
    _registered_routines.add(routine.id)


def _register_reminder(
    scheduler: AsyncIOScheduler,
    owner: discord.User,
    agent: Agent,
    reminder: Reminder,
) -> None:
    if reminder.id in _registered_reminders:
        return

    async def fire_oneshot() -> None:
        busy = agent.lock().locked()
        bg_config: BgForkConfig | None = None
        all_reminders: list[Reminder] = []
        all_routines: list[Routine] = []
        if reminder.background:
            from ollim_bot.tool_policy import validate_dispatch

            bg_config = BgForkConfig.from_item(reminder)
            bg_config = _merge_skill_tools(bg_config, reminder.skills)
            if not validate_dispatch(bg_config.allowed_tools, source=reminder.id):
                return
            all_reminders = list_reminders()
            all_routines = list_routines()
        sname = ensure_skill(reminder)
        prompt = build_reminder_prompt(
            reminder,
            skill_name=sname,
            reminders=all_reminders,
            routines=all_routines,
            busy=busy,
            bg_config=bg_config,
            overdue_at=overdue_at,
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
                    thinking=thinking_mode(reminder.thinking),
                    isolated=reminder.isolated,
                    bg_config=bg_config,
                )
            else:
                if reminder.model or reminder.isolated:
                    log.warning(
                        "Reminder %s: model/isolated only apply to background reminders",
                        reminder.id,
                    )
                await send_agent_dm(agent, prompt, chain_ctx=chain_ctx)
        except Exception:
            log.exception("Reminder %s failed", reminder.id)
            raise
        finally:
            set_chain_context(None)
            await asyncio.to_thread(remove_reminder, reminder.id)
            _registered_reminders.discard(reminder.id)

    run_at = datetime.fromisoformat(reminder.run_at)
    now = datetime.now(TZ)
    overdue_at: datetime | None = None
    if run_at < now:
        overdue_at = run_at
        run_at = now + timedelta(seconds=5)

    try:
        scheduler.add_job(fire_oneshot, DateTrigger(run_date=run_at), id=f"rem_{reminder.id}")
    except (ValueError, KeyError):
        log.exception("Failed to register reminder %s (run_at: %s)", reminder.id, reminder.run_at)
        problem_key = f"reminder_reg_{reminder.id}"
        if problem_key not in _reported_problems:
            _reported_problems.add(problem_key)
            asyncio.get_event_loop().create_task(
                append_update(f"Reminder **{reminder.id}** failed to register — invalid run_at `{reminder.run_at}`")
            )
        return
    _registered_reminders.add(reminder.id)


_INTERNAL_JOBS = {"sync_all", "check_fork_timeout", "check_for_update"}


def _on_job_missed(event: JobExecutionEvent) -> None:
    job_id: str = event.job_id
    if job_id in _INTERNAL_JOBS:
        return

    if job_id.startswith("routine_"):
        kind, name = "routine", job_id.removeprefix("routine_")
    elif job_id.startswith("rem_"):
        kind, name = "reminder", job_id.removeprefix("rem_")
    else:
        return

    scheduled = event.scheduled_run_time.astimezone(TZ).strftime("%I:%M %p").lstrip("0")
    msg = f"Missed {kind} **{name}** (was due {scheduled})"
    asyncio.get_event_loop().create_task(append_update(msg))


def setup_scheduler(bot: discord.Client, agent: Agent, owner: discord.User) -> AsyncIOScheduler:
    """Polls routines/reminders every 10s, registering new and pruning stale jobs."""
    scheduler = AsyncIOScheduler(timezone=str(TZ))
    scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)

    @scheduler.scheduled_job(IntervalTrigger(seconds=10))
    async def sync_all() -> None:
        routine_files = sorted(ROUTINES_DIR.glob("*.md")) if ROUTINES_DIR.is_dir() else []
        current_routines = list_routines()
        current_routine_ids = {r.id for r in current_routines}
        _check_corrupt_files(len(current_routines), "routine", routine_files)
        for routine in current_routines:
            _register_routine(scheduler, owner, agent, routine)
        stale_routine_ids = _registered_routines - current_routine_ids
        for stale_id in stale_routine_ids:
            job = scheduler.get_job(f"routine_{stale_id}")
            if job:
                job.remove()
            _registered_routines.discard(stale_id)
            _reported_problems.discard(f"routine_reg_{stale_id}")

        reminder_files = sorted(REMINDERS_DIR.glob("*.md")) if REMINDERS_DIR.is_dir() else []
        current_reminders = list_reminders()
        current_reminder_ids = {r.id for r in current_reminders}
        _check_corrupt_files(len(current_reminders), "reminder", reminder_files)
        for reminder in current_reminders:
            _register_reminder(scheduler, owner, agent, reminder)
        stale_reminder_ids = _registered_reminders - current_reminder_ids
        for stale_id in stale_reminder_ids:
            job = scheduler.get_job(f"rem_{stale_id}")
            if job:
                job.remove()
            _registered_reminders.discard(stale_id)
            _reported_problems.discard(f"reminder_reg_{stale_id}")

        if stale_routine_ids or stale_reminder_ids:
            active = {f"routine-{r.id}" for r in current_routines} | {f"reminder-{r.id}" for r in current_reminders}
            cleanup_stale_skills(active)

        _ch = get_channel()
        if _ch and check_and_clear_revoked():
            await _ch.send("-# google auth revoked — use /google-auth to reconnect.")

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
            start_message_collector()
            await dm.send("-# fork idle — checking in...")
            await dm.typing()
            await stream_to_channel(dm, agent.stream_chat(prompt))
            sid = agent.fork_session_id
            if sid:
                flush_message_collector(sid, load_session_id())
            else:
                cancel_message_collector()
            result = await agent.pop_fork_exit()
            if result:
                action, summary = result
                await dm.send(embed=fork_exit_embed(action, summary))
            else:
                touch_activity()

    _last_update_check = 0.0

    @scheduler.scheduled_job(IntervalTrigger(minutes=5))
    async def check_for_update() -> None:
        nonlocal _last_update_check

        from ollim_bot import runtime_config

        cfg = runtime_config.load()
        if not cfg.auto_update:
            return

        now = time.monotonic()
        if now - _last_update_check < cfg.auto_update_interval * 60:
            return

        _last_update_check = now
        await _do_update_check(cfg)

    async def _do_update_check(cfg: RuntimeConfig) -> None:
        from ollim_bot.fork_state import in_interactive_fork
        from ollim_bot.storage import PROJECT_DIR
        from ollim_bot.updater import (
            apply_update,
            check_for_updates,
            format_commit_summary,
            format_error,
            log_and_restart,
        )

        try:
            status = await asyncio.to_thread(check_for_updates, PROJECT_DIR)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            log.warning("auto-update: git fetch failed")
            return

        if not status.available:
            return

        if agent.lock().locked() or in_interactive_fork():
            log.info("auto-update: deferred (agent busy)")
            return

        if datetime.now(TZ).hour != cfg.auto_update_hour:
            log.info("auto-update: waiting for %d:00", cfg.auto_update_hour)
            return

        log.info(
            "auto-update: %s -> %s",
            status.local_sha[:8],
            status.remote_sha[:8],
        )
        dm = await owner.create_dm()

        try:
            await asyncio.to_thread(apply_update, PROJECT_DIR)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("auto-update: failed: %s", exc)
            await dm.send(f"auto-update failed: {format_error(exc)}")
            return

        summary = format_commit_summary(status.commit_summary)
        await dm.send(f"updating and restarting...\n```\n{summary}\n```")

        log_and_restart()

    return scheduler
