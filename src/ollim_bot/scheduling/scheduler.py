"""Proactive routines and reminders via APScheduler.

Polls routines.jsonl and reminders.jsonl every 10s, registers APScheduler jobs.
Routines use CronTrigger, reminders use DateTrigger (one-shot, auto-removed).
Chain reminders inject chain context so the agent can call follow_up_chain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """One upcoming bg task in the forward schedule."""

    id: str
    fire_time: datetime
    label: str  # e.g. "Chore-time routine" or "Chain reminder (2/4)"
    description: str  # from YAML description or truncated message
    file_path: str  # relative path for agent to Read
    silent: bool = False  # allow_ping=False
    tag: str | None = None  # "this task", "just fired", or None


_GRACE_MINUTES = 15
_BASE_WINDOW_HOURS = 3
_MIN_FORWARD = 3
_MAX_WINDOW_HOURS = 12
_TRUNCATE_LEN = 60


def _routine_next_fire(routine: Routine, after: datetime) -> datetime | None:
    """Get next fire time for a routine after a given datetime."""
    parts = routine.cron.split()
    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=_convert_dow(parts[4]),
    )
    return trigger.get_next_fire_time(None, after)


def _routine_prev_fire(routine: Routine, now: datetime) -> datetime | None:
    """Get most recent fire time for a routine within the grace window."""
    grace_start = now - timedelta(minutes=_GRACE_MINUTES)
    nxt = _routine_next_fire(routine, grace_start)
    if nxt is not None and nxt <= now:
        return nxt
    return None


def _entry_description(item: Routine | Reminder) -> str:
    """Use YAML description if available, else truncate message."""
    if item.description:
        return item.description
    msg = item.message.replace("\n", " ").strip()
    if len(msg) <= _TRUNCATE_LEN:
        return msg
    return msg[:_TRUNCATE_LEN] + "..."


def _entry_label(item: Routine | Reminder) -> str:
    """Build the label prefix."""
    if isinstance(item, Routine):
        return item.description or "Routine"
    if item.max_chain > 0:
        check = item.chain_depth + 1
        total = item.max_chain + 1
        return f"Chain reminder ({check}/{total})"
    return "Reminder"


def _entry_file_path(item: Routine | Reminder) -> str:
    """Relative file path for the agent to Read."""
    if isinstance(item, Routine):
        return f"routines/{item.id}.md"
    return f"reminders/{item.id}.md"


def _build_upcoming_schedule(
    routines: list[Routine],
    reminders: list[Reminder],
    *,
    current_id: str,
) -> list[ScheduleEntry]:
    """Build the forward schedule for the bg preamble."""
    now = datetime.now(TZ)
    base_cutoff = now + timedelta(hours=_BASE_WINDOW_HOURS)
    max_cutoff = now + timedelta(hours=_MAX_WINDOW_HOURS)
    grace_start = now - timedelta(minutes=_GRACE_MINUTES)

    candidates: list[tuple[datetime, Routine | Reminder]] = []

    for r in routines:
        if not r.background:
            continue
        prev = _routine_prev_fire(r, now)
        if prev is not None:
            candidates.append((prev, r))
        nxt = _routine_next_fire(r, now)
        if nxt is not None and nxt <= max_cutoff:
            candidates.append((nxt, r))

    for rem in reminders:
        if not rem.background:
            continue
        fire = datetime.fromisoformat(rem.run_at)
        if grace_start <= fire <= max_cutoff:
            candidates.append((fire, rem))

    candidates.sort(key=lambda x: x[0])

    # Apply dynamic window: all within base_cutoff, extend for min forward count
    forward = [(t, item) for t, item in candidates if t > now]
    recent = [(t, item) for t, item in candidates if t <= now]

    if len(forward) < _MIN_FORWARD:
        selected_forward = forward
    else:
        in_window = [(t, item) for t, item in forward if t <= base_cutoff]
        if len(in_window) >= _MIN_FORWARD:
            selected_forward = in_window
        else:
            selected_forward = forward[:_MIN_FORWARD]

    selected = recent + selected_forward

    entries: list[ScheduleEntry] = []
    for fire_time, item in selected:
        if item.id == current_id:
            tag = "this task"
        elif fire_time <= now:
            tag = "just fired"
        else:
            tag = None
        entries.append(
            ScheduleEntry(
                id=item.id,
                fire_time=fire_time,
                label=_entry_label(item),
                description=_entry_description(item),
                file_path=_entry_file_path(item),
                silent=not item.allow_ping,
                tag=tag,
            )
        )

    return entries


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
    schedule: list[ScheduleEntry],
    *,
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    """Build BG_PREAMBLE with budget status, schedule, and config."""
    now = datetime.now(TZ)
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

        # --- Schedule ---
        if schedule:
            last_forward = [e for e in schedule if e.tag != "just fired"]
            if last_forward:
                hours = (last_forward[-1].fire_time - now).total_seconds() / 3600
                window_label = f"next {max(1, round(hours))}h"
            else:
                window_label = "recent"
            schedule_lines = [f"Upcoming bg tasks ({window_label}):"]
            for entry in schedule:
                time_str = entry.fire_time.strftime("%-I:%M %p")
                silent = " (silent)" if entry.silent else ""
                tag_str = f" [{entry.tag}]" if entry.tag else ""
                schedule_lines.append(
                    f"- {time_str}: {entry.label}{silent} — "
                    f'"{entry.description}" ({entry.file_path}){tag_str}'
                )
            if last_forward:
                minutes_to_last = (
                    last_forward[-1].fire_time - now
                ).total_seconds() / 60
                refill_rate = ping_budget.load().refill_rate_minutes
                refills = int(minutes_to_last / refill_rate)
                if refills > 0:
                    s = "s" if refills != 1 else ""
                    schedule_lines.append(f"~{refills} refill{s} before last task.")
            schedule_section = "\n".join(schedule_lines) + "\n"
        else:
            schedule_section = "No more bg tasks today.\n"

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
            f"{schedule_section}"
            f"Send at most 1 ping or embed per bg session.\n"
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
    elif config.disallowed_tools is not None:
        tools_section = (
            "TOOL RESTRICTIONS: These tools are NOT available for this task:\n"
            + "\n".join(f"  - {t}" for t in config.disallowed_tools)
            + "\n\n"
        )
    else:
        tools_section = ""

    return f"{ping_section}{update_section}{busy_line}{budget_section}{tools_section}"


def _build_routine_prompt(
    routine: Routine,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    if routine.background:
        schedule = _build_upcoming_schedule(routines, reminders, current_id=routine.id)
        preamble = _build_bg_preamble(schedule, busy=busy, bg_config=bg_config)
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
        schedule = _build_upcoming_schedule(routines, reminders, current_id=reminder.id)
        parts.append(
            _build_bg_preamble(schedule, busy=busy, bg_config=bg_config).rstrip()
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
            disallowed_tools=routine.disallowed_tools,
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
            disallowed_tools=reminder.disallowed_tools,
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
                disallowed_tools=reminder.disallowed_tools,
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
