"""Discord UI views and persistent button handlers."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import discord
from discord.ui import Button, DynamicItem, View

from ollim_bot import inquiries
from ollim_bot.discord_tools import set_channel
from ollim_bot.embed_types import ButtonConfig, EmbedConfig
from ollim_bot.google_auth import get_service
from ollim_bot.streamer import stream_to_channel

if TYPE_CHECKING:
    from ollim_bot.agent import Agent

# Module-level references, set by bot.py on startup via init()
_agent: Agent | None = None

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


def init(agent: Agent) -> None:
    """Store agent reference for button callbacks. Call from bot.py on_ready."""
    global _agent
    _agent = agent


_EMOJI_RE = re.compile(
    r"[\U0001f300-\U0001faff\u2600-\u27bf\u23e9-\u23fa\ufe0f\u200d]+\s*",
)


def build_embed(config: EmbedConfig) -> discord.Embed:
    """Build a discord.Embed from an EmbedConfig."""
    color = COLOR_MAP.get(config.color, discord.Color.blue())
    title = _EMOJI_RE.sub("", config.title).strip() if config.title else None
    embed = discord.Embed(
        title=title,
        description=config.description,
        color=color,
    )
    for ef in config.fields:
        embed.add_field(name=ef.name, value=ef.value, inline=ef.inline)
    return embed


def build_view(buttons: list[ButtonConfig]) -> View | None:
    """Build a persistent View from button configs."""
    if not buttons:
        return None
    view = View(timeout=None)
    for btn in buttons[:25]:
        action = btn.action
        style = STYLE_MAP.get(btn.style, discord.ButtonStyle.secondary)

        # For agent inquiry, store the prompt and replace with uuid
        if action.startswith("agent:"):
            uid = inquiries.register(action[6:])
            custom_id = f"act:agent:{uid}"
        elif ":" in action:
            custom_id = f"act:{action}"
        else:
            custom_id = f"act:{action}:_"

        view.add_item(
            ActionButton(
                discord.ui.Button(label=btn.label, style=style, custom_id=custom_id),
            )
        )
    return view


class ActionButton(
    DynamicItem[Button], template=r"act:(?P<action>[a-z_]+):(?P<data>.+)"
):
    """Persistent button that dispatches to action handlers."""

    def __init__(self, button: Button):
        super().__init__(button)
        self.action: str = ""
        self.data: str = ""

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: Button,
        match: re.Match[str],
    ) -> ActionButton:
        inst = cls(item)
        inst.action = match.group("action")
        inst.data = match.group("data")
        return inst

    async def callback(self, interaction: discord.Interaction) -> None:
        handlers = {
            "task_done": _handle_task_done,
            "task_del": _handle_task_delete,
            "event_del": _handle_event_delete,
            "agent": _handle_agent_inquiry,
            "dismiss": _handle_dismiss,
        }
        handler = handlers.get(self.action)
        if handler:
            await handler(interaction, self.data)
        else:
            await interaction.response.send_message("unknown action", ephemeral=True)


def _complete_task(task_id: str) -> None:
    get_service("tasks", "v1").tasks().patch(
        tasklist="@default",
        task=task_id,
        body={"status": "completed"},
    ).execute()


def _delete_task(task_id: str) -> None:
    get_service("tasks", "v1").tasks().delete(
        tasklist="@default", task=task_id
    ).execute()


def _delete_event(event_id: str) -> None:
    get_service("calendar", "v3").events().delete(
        calendarId="primary",
        eventId=event_id,
    ).execute()


async def _handle_task_done(interaction: discord.Interaction, task_id: str) -> None:
    await asyncio.to_thread(_complete_task, task_id)
    await interaction.response.send_message("done ✓", ephemeral=True)


async def _handle_task_delete(interaction: discord.Interaction, task_id: str) -> None:
    await asyncio.to_thread(_delete_task, task_id)
    await interaction.response.send_message("deleted", ephemeral=True)


async def _handle_event_delete(interaction: discord.Interaction, event_id: str) -> None:
    await asyncio.to_thread(_delete_event, event_id)
    await interaction.response.send_message("deleted", ephemeral=True)


async def _handle_agent_inquiry(
    interaction: discord.Interaction, inquiry_id: str
) -> None:
    prompt = inquiries.pop(inquiry_id)
    if not prompt:
        await interaction.response.send_message(
            "this button has expired.", ephemeral=True
        )
        return

    await interaction.response.defer()
    user_id = str(interaction.user.id)
    async with _agent.lock(user_id):
        set_channel(interaction.channel)
        await interaction.channel.typing()
        await stream_to_channel(
            interaction.channel,
            _agent.stream_chat(f"[button] {prompt}", user_id=user_id),
        )


async def _handle_dismiss(interaction: discord.Interaction, _data: str) -> None:
    await interaction.message.delete()
