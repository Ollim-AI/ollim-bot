"""MCP tool definitions for reminder management (add, list, cancel)."""

import asyncio
from datetime import datetime
from typing import Any

from claude_agent_sdk import tool

from ollim_bot.config import TZ
from ollim_bot.scheduling.reminders import Reminder, append_reminder, remove_reminder
from ollim_bot.scheduling.reminders import list_reminders as _list_reminders


def _resp(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "add_reminder",
    "Schedule a one-shot reminder. Reminders are background by default — "
    "the agent pings you at fire time. Write the prompt as instructions for "
    "yourself (you receive it as [reminder-bg:ID]).",
    {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Prompt for your future self. Include all context needed at fire time.",
            },
            "delay_minutes": {
                "type": "integer",
                "description": "Fire in N minutes from now. Provide this OR run_at, not both.",
            },
            "run_at": {
                "type": "string",
                "description": (
                    "ISO datetime to fire at (e.g. '2026-03-13T15:00'). "
                    "Uses bot timezone if no offset given. Provide this OR delay_minutes, not both."
                ),
            },
            "description": {
                "type": "string",
                "description": "Short summary shown in reminder list",
            },
            "foreground": {
                "type": "boolean",
                "description": (
                    "Almost never needed. Use ONLY when the user wants to watch "
                    "tool actions stream at fire time (transparent execution). "
                    "Do NOT use for notifications, nudges, or alerts — background "
                    "with ping_user handles those. If the user might want to "
                    "discuss the result, they reply to the bg ping (starts an "
                    "interactive fork)."
                ),
            },
            "max_chain": {
                "type": "integer",
                "description": "Max follow-up chain depth (0 = plain one-shot)",
            },
        },
        "required": ["prompt"],
    },
)
async def add_reminder(args: dict[str, Any]) -> dict[str, Any]:
    prompt = args["prompt"]
    delay = args.get("delay_minutes")
    run_at_str = args.get("run_at")

    if delay is not None and run_at_str is not None:
        return _resp("Error: provide delay_minutes OR run_at, not both.")
    if delay is None and run_at_str is None:
        return _resp("Error: provide either delay_minutes or run_at.")

    if run_at_str is not None:
        try:
            run_at_dt = datetime.fromisoformat(run_at_str)
        except ValueError:  # user input — fromisoformat has no non-throwing variant
            return _resp(f"Error: invalid ISO datetime: {run_at_str}")
        if run_at_dt.tzinfo is None:
            run_at_dt = run_at_dt.replace(tzinfo=TZ)
        now = datetime.now(TZ)
        diff = (run_at_dt - now).total_seconds()
        if diff < 0:
            return _resp("Error: run_at is in the past.")
        delay = max(1, int(diff / 60))

    assert delay is not None  # guaranteed by validation above
    foreground = args.get("foreground", False)
    reminder = Reminder.new(
        message=prompt,
        delay_minutes=delay,
        background=not foreground,
        description=args.get("description", ""),
        max_chain=args.get("max_chain", 0),
    )
    await asyncio.to_thread(append_reminder, reminder)

    fire_dt = datetime.fromisoformat(reminder.run_at)
    fire_str = fire_dt.strftime("%I:%M %p").lstrip("0")
    return _resp(f"Reminder {reminder.id} set for {fire_str}.")


@tool(
    "list_reminders",
    "List all pending reminders with their IDs, scheduled times, and descriptions.",
    {"type": "object", "properties": {}},
)
async def list_reminders_tool(args: dict[str, Any]) -> dict[str, Any]:
    reminders = _list_reminders()
    if not reminders:
        return _resp("No pending reminders.")

    lines = []
    for r in sorted(reminders, key=lambda r: r.run_at):
        fire_dt = datetime.fromisoformat(r.run_at)
        time_str = fire_dt.strftime("%Y-%m-%d %I:%M %p")
        mode = "fg" if not r.background else "bg"
        desc = r.description or "(no description)"
        lines.append(f"- {r.id} [{mode}] {time_str} — {desc}  (reminders/{r.id}.md)")
    return _resp("\n".join(lines))


@tool(
    "cancel_reminder",
    "Cancel a pending reminder by ID.",
    {
        "type": "object",
        "properties": {
            "reminder_id": {
                "type": "string",
                "description": "Reminder ID to cancel",
            },
        },
        "required": ["reminder_id"],
    },
)
async def cancel_reminder(args: dict[str, Any]) -> dict[str, Any]:
    reminder_id = args["reminder_id"]
    removed = await asyncio.to_thread(remove_reminder, reminder_id)
    if removed:
        return _resp(f"Reminder {reminder_id} cancelled.")
    return _resp(f"Error: no reminder found with ID {reminder_id}.")
