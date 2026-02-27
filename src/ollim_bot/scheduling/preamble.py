"""Bg preamble and forward schedule builder for bg fork prompts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger

from ollim_bot import ping_budget
from ollim_bot.config import TZ
from ollim_bot.forks import BgForkConfig
from ollim_bot.scheduling.reminders import Reminder
from ollim_bot.scheduling.routines import Routine

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
        timezone=str(TZ),
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


def build_upcoming_schedule(
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


def build_bg_preamble(
    schedule: list[ScheduleEntry],
    *,
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
    persistent: bool = False,
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
            "This runs on a forked session. This task runs silently -- no reporting to the main session.\n\n"
        )
    else:  # on_ping (default)
        update_section = (
            "This runs on a forked session -- by default everything is discarded.\n"
            "- Call `report_updates(message)` to update the main session on what "
            "happened (fork discarded).\n"
            "- If you send a ping or embed, you MUST also call `report_updates`.\n"
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
                    f'- {time_str}: {entry.label}{silent} — "{entry.description}" ({entry.file_path}){tag_str}'
                )
            if last_forward:
                minutes_to_last = (last_forward[-1].fire_time - now).total_seconds() / 60
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

    persistent_section = (
        "SESSION: Persistent — your context carries across fires. "
        "You have a `compact_session` tool to compress context when it grows large.\n\n"
        if persistent
        else ""
    )

    return f"{persistent_section}{ping_section}{update_section}{busy_line}{budget_section}{tools_section}"


def build_routine_prompt(
    routine: Routine,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
    persistent: bool = False,
) -> str:
    if routine.background:
        schedule = build_upcoming_schedule(routines, reminders, current_id=routine.id)
        preamble = build_bg_preamble(schedule, busy=busy, bg_config=bg_config, persistent=persistent)
        return f"[routine-bg:{routine.id}] {preamble}{routine.message}"
    return f"[routine:{routine.id}] {routine.message}"


def build_reminder_prompt(
    reminder: Reminder,
    *,
    reminders: list[Reminder],
    routines: list[Routine],
    busy: bool = False,
    bg_config: BgForkConfig | None = None,
) -> str:
    tag = f"reminder-bg:{reminder.id}" if reminder.background else f"reminder:{reminder.id}"
    parts = [f"[{tag}]"]

    if reminder.background:
        schedule = build_upcoming_schedule(routines, reminders, current_id=reminder.id)
        parts.append(build_bg_preamble(schedule, busy=busy, bg_config=bg_config).rstrip())

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
