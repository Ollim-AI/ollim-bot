"""Discord UI views and persistent button handlers."""

import asyncio
from uuid import uuid4

import discord
from discord.ui import Button, DynamicItem, View

from ollim_bot.google_auth import get_service
from ollim_bot.streamer import stream_to_channel

# Module-level references, set by bot.py on startup via init()
_agent = None

_followup_prompts: dict[str, str] = {}

STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}

COLOR_MAP = {
    "blue": discord.Color.blue(),
    "green": discord.Color.green(),
    "red": discord.Color.red(),
    "yellow": discord.Color.yellow(),
    "purple": discord.Color.purple(),
}


def init(agent) -> None:
    """Store agent reference for button callbacks. Call from bot.py on_ready."""
    global _agent
    _agent = agent


def register_followup(prompt: str) -> str:
    """Store a prompt for agent followup, return its short ID."""
    uid = uuid4().hex[:8]
    _followup_prompts[uid] = prompt
    return uid


def build_embed(args: dict) -> discord.Embed:
    """Build a discord.Embed from tool args."""
    color = COLOR_MAP.get(args.get("color", "blue"), discord.Color.blue())
    embed = discord.Embed(
        title=args.get("title"),
        description=args.get("description"),
        color=color,
    )
    for field in args.get("fields", []):
        embed.add_field(
            name=field.get("name", "\u200b"),
            value=field.get("value", "\u200b"),
            inline=field.get("inline", True),
        )
    return embed


def build_view(buttons: list[dict]) -> View | None:
    """Build a persistent View from button configs."""
    if not buttons:
        return None
    view = View(timeout=None)
    for btn in buttons[:25]:
        action = btn.get("action", "dismiss:_")
        style = STYLE_MAP.get(btn.get("style", "secondary"), discord.ButtonStyle.secondary)

        # For agent followup, store the prompt and replace with uuid
        if action.startswith("agent:"):
            uid = register_followup(action[6:])
            custom_id = f"act:agent:{uid}"
        elif ":" in action:
            custom_id = f"act:{action}"
        else:
            custom_id = f"act:{action}:_"

        view.add_item(ActionButton(
            discord.ui.Button(label=btn.get("label", ""), style=style, custom_id=custom_id),
        ))
    return view


class ActionButton(DynamicItem[Button], template=r"act:(?P<action>[a-z_]+):(?P<data>.+)"):
    """Persistent button that dispatches to action handlers."""

    def __init__(self, button: Button):
        super().__init__(button)
        self.action: str = ""
        self.data: str = ""

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        inst = cls(item)
        inst.action = match.group("action")
        inst.data = match.group("data")
        return inst

    async def callback(self, interaction: discord.Interaction):
        handlers = {
            "task_done": _handle_task_done,
            "task_del": _handle_task_delete,
            "event_del": _handle_event_delete,
            "agent": _handle_agent_followup,
            "dismiss": _handle_dismiss,
        }
        handler = handlers.get(self.action)
        if handler:
            await handler(interaction, self.data)
        else:
            await interaction.response.send_message("unknown action", ephemeral=True)


def _complete_task(task_id: str) -> None:
    get_service("tasks", "v1").tasks().patch(
        tasklist="@default", task=task_id, body={"status": "completed"},
    ).execute()


def _delete_task(task_id: str) -> None:
    get_service("tasks", "v1").tasks().delete(tasklist="@default", task=task_id).execute()


def _delete_event(event_id: str) -> None:
    get_service("calendar", "v3").events().delete(
        calendarId="primary", eventId=event_id,
    ).execute()


async def _handle_task_done(interaction: discord.Interaction, task_id: str):
    await asyncio.to_thread(_complete_task, task_id)
    await interaction.response.send_message("done ✓", ephemeral=True)


async def _handle_task_delete(interaction: discord.Interaction, task_id: str):
    await asyncio.to_thread(_delete_task, task_id)
    await interaction.response.send_message("deleted", ephemeral=True)


async def _handle_event_delete(interaction: discord.Interaction, event_id: str):
    await asyncio.to_thread(_delete_event, event_id)
    await interaction.response.send_message("deleted", ephemeral=True)


async def _handle_agent_followup(interaction: discord.Interaction, followup_id: str):
    prompt = _followup_prompts.pop(followup_id, None)
    if not prompt:
        await interaction.response.send_message("this button has expired.", ephemeral=True)
        return

    await interaction.response.defer()
    user_id = str(interaction.user.id)
    async with _agent.lock(user_id):
        await interaction.channel.typing()
        await stream_to_channel(
            interaction.channel,
            _agent.stream_chat(f"[button] {prompt}", user_id=user_id),
        )


async def _handle_dismiss(interaction: discord.Interaction, _data: str):
    await interaction.message.delete()
