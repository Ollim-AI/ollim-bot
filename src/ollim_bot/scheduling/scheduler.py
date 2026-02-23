"""Proactive routines and reminders via APScheduler.

Polls routines.jsonl and reminders.jsonl every 10s, registers APScheduler jobs.
Routines use CronTrigger, reminders use DateTrigger (one-shot, auto-removed).
Chain reminders inject chain context so the agent can call follow_up_chain.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ollim_bot import permissions, ping_budget
from ollim_bot.agent_tools import (
    ChainContext,
    set_chain_context,
    set_channel,
    set_fork_chain_context,
)
from ollim_bot.config import USER_NAME
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
from ollim_bot.scheduling.reminders import Reminder, list_reminders, remove_reminder
from ollim_bot.scheduling.routines import Routine, list_routines
from ollim_bot.streamer import stream_to_channel

if TYPE_CHECKING:
    from ollim_bot.agent import Agent

TZ = ZoneInfo("America/Los_Angeles")
log = logging.getLogger(__name__)

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


def _fires_before_midnight(cron: str) -> bool:
    """Check whether a cron expression fires between now and midnight."""
    parts = cron.split()
    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=_convert_dow(parts[4]),
    )
    now = datetime.now(TZ)
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    next_fire = trigger.get_next_fire_time(None, now)
    return next_fire is not None and next_fire < midnight


def _remaining_bg_routine_firings(routines: list[Routine]) -> int:
    """Count bg routines with allow_ping that fire between now and midnight."""
    return sum(
        1
        for r in routines
        if r.background and r.allow_ping and _fires_before_midnight(r.cron)
    )


def _build_bg_preamble(
    bg_reminders_remaining: int,
    bg_routines_remaining: int,
    *,
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    """Build BG_PREAMBLE with budget status, remaining task count, and config."""
    config = bg_config or BgForkConfig()

    # --- Ping instructions ---
    if config.allow_ping:
        ping_section = (
            "Your text output will be discarded. Use `ping_user` (MCP tool) to send "
            "a plain text alert, or `discord_embed` for structured data. Only alert "
            "if something genuinely warrants attention.\n\n"
        )
    else:
        ping_section = (
            "Your text output will be discarded. "
            "Pinging is disabled for this task — `ping_user` and `discord_embed` "
            "are not available.\n\n"
        )

    # --- Update instructions ---
    mode = config.update_main_session
    if mode == "always":
        update_section = (
            "This runs on a forked session -- by default everything is discarded.\n"
            "You MUST call `report_updates(message)` before finishing to update "
            "the main session on what happened.\n\n"
        )
    elif mode == "freely":
        update_section = (
            "This runs on a forked session -- by default everything is discarded.\n"
            "You may optionally call `report_updates(message)` to update the main "
            "session on what happened -- or just finish without it.\n\n"
        )
    elif mode == "blocked":
        update_section = (
            "This runs on a forked session. This task runs silently -- no "
            "reporting to the main session.\n\n"
        )
    else:  # on_ping (default)
        update_section = (
            "This runs on a forked session -- by default everything is discarded.\n"
            "- Call `report_updates(message)` to update the main session on what "
            "happened (fork discarded).\n"
            "- Call nothing if nothing useful happened.\n\n"
        )

    busy_line = (
        "User is mid-conversation. Do NOT use `ping_user` or `discord_embed` "
        "unless `critical=True`. Use `report_updates` for all findings -- "
        "they'll appear in the main session when the conversation ends.\n\n"
        if busy and config.allow_ping
        else ""
    )

    if config.allow_ping:
        budget_status = ping_budget.get_status()
        remaining_parts: list[str] = []
        if bg_reminders_remaining > 0:
            remaining_parts.append(
                f"{bg_reminders_remaining} bg reminder{'s' if bg_reminders_remaining != 1 else ''}"
            )
        if bg_routines_remaining > 0:
            remaining_parts.append(
                f"{bg_routines_remaining} bg routine{'s' if bg_routines_remaining != 1 else ''}"
            )
        remaining_line = (
            f"Still to fire today: {', '.join(remaining_parts)}.\n"
            if remaining_parts
            else ""
        )
        can_report = config.update_main_session != "blocked"
        if can_report:
            regret_line = (
                "Before pinging, ask: would the user regret missing this? "
                "Informational summaries and low-stakes check-ins → report_updates. "
                "Time-sensitive actions, accountability nudges, health routines → ping.\n"
                "When budget is tight, save pings for tasks the user would regret missing. "
            )
        else:
            regret_line = (
                "Before pinging, ask: would the user regret missing this? "
                "Skip low-stakes check-ins. "
                "Time-sensitive actions, accountability nudges, health routines → ping.\n"
            )
        budget_section = (
            f"Ping budget: {budget_status}.\n"
            f"{remaining_line}"
            f"Send at most 1 ping or embed per bg session — multiple routines share the daily budget. "
            f"If budget is 0, do not attempt to ping.\n"
            f"{regret_line}"
            f"critical=True bypasses the budget — reserve for things the user would be devastated to miss.\n\n"
        )
    else:
        budget_section = ""

    # --- Tool restrictions ---
    if config.allowed_tools is not None:
        tools_section = (
            "TOOL RESTRICTIONS: Only these tools are available for this task:\n"
            + "\n".join(f"  - {t}" for t in config.allowed_tools)
            + "\n\n"
        )
    elif config.blocked_tools is not None:
        tools_section = (
            "TOOL RESTRICTIONS: These tools are NOT available for this task:\n"
            + "\n".join(f"  - {t}" for t in config.blocked_tools)
            + "\n\n"
        )
    else:
        tools_section = ""

    return f"{ping_section}{update_section}{busy_line}{budget_section}{tools_section}"


def _compute_remaining(
    reminders: list[Reminder], routines: list[Routine]
) -> tuple[int, int]:
    """Compute (bg_reminders_remaining, bg_routines_remaining) for preamble."""
    return (
        ping_budget.remaining_bg_reminders(reminders),
        _remaining_bg_routine_firings(routines),
    )


def _build_routine_prompt(
    routine: Routine,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    if routine.background:
        bg_rem, bg_rtn = _compute_remaining(reminders, routines)
        preamble = _build_bg_preamble(bg_rem, bg_rtn, busy=busy, bg_config=bg_config)
        return f"[routine-bg:{routine.id}] {preamble}{routine.message}"
    return f"[routine:{routine.id}] {routine.message}"


def _build_reminder_prompt(
    reminder: Reminder,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    tag = (
        f"reminder-bg:{reminder.id}"
        if reminder.background
        else f"reminder:{reminder.id}"
    )
    parts = [f"[{tag}]"]

    if reminder.background:
        bg_rem, bg_rtn = _compute_remaining(reminders, routines)
        parts.append(
            _build_bg_preamble(bg_rem, bg_rtn, busy=busy, bg_config=bg_config).rstrip()
        )

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
        bg_config = BgForkConfig(
            update_main_session=routine.update_main_session,
            allow_ping=routine.allow_ping,
            allowed_tools=routine.allowed_tools,
            blocked_tools=routine.blocked_tools,
        )
        prompt = _build_routine_prompt(
            routine,
            reminders=list_reminders(),
            routines=list_routines(),
            busy=busy,
            bg_config=bg_config,
        )
        try:
            if routine.background:
                await run_agent_background(
                    owner,
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
                await send_agent_dm(owner, agent, prompt)
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
        bg_config = BgForkConfig(
            update_main_session=reminder.update_main_session,
            allow_ping=reminder.allow_ping,
            allowed_tools=reminder.allowed_tools,
            blocked_tools=reminder.blocked_tools,
        )
        prompt = _build_reminder_prompt(
            reminder,
            reminders=list_reminders(),
            routines=list_routines(),
            busy=busy,
            bg_config=bg_config,
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
                blocked_tools=reminder.blocked_tools,
            )

        try:
            if reminder.background:
                if chain_ctx:
                    set_fork_chain_context(chain_ctx)
                await run_agent_background(
                    owner,
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
                await send_agent_dm(owner, agent, prompt)
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

    scheduler.add_job(
        fire_oneshot, DateTrigger(run_date=run_at), id=f"rem_{reminder.id}"
    )


def setup_scheduler(
    bot: discord.Client, agent: Agent, owner: discord.User
) -> AsyncIOScheduler:
    """Polls routines/reminders every 10s, registering new and pruning stale jobs."""
    scheduler = AsyncIOScheduler(timezone="America/Los_Angeles")

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
                f"[fork-timeout] REMINDER: This fork has been idle for over {timeout * 2} minutes "
                "and you already received a timeout notice. You MUST exit now: "
                "use `save_context`, `report_updates(message)`, or `exit_fork`."
            )
        else:
            prompt = (
                f"[fork-timeout] This fork has been idle for {timeout} minutes. "
                "Decide what to do: use `save_context` to promote to main session, "
                "`report_updates(message)` to send a summary, or `exit_fork` to discard. "
                f"If {USER_NAME} is still engaged, ask them what they'd like to do."
            )

        async with agent.lock():
            set_channel(dm)
            permissions.set_channel(dm)
            await dm.typing()
            await stream_to_channel(dm, agent.stream_chat(prompt))
            result = await agent.pop_fork_exit()
            if result:
                action, summary = result
                await dm.send(embed=fork_exit_embed(action, summary))
            else:
                touch_activity()

    return scheduler
