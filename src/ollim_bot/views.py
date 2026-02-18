"""Discord UI views and persistent button handlers."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import discord
from discord.ui import Button, DynamicItem

from ollim_bot import inquiries
from ollim_bot.google.calendar import delete_event
from ollim_bot.google.tasks import complete_task, delete_task
from ollim_bot.streamer import dispatch_agent_response

if TYPE_CHECKING:
    from ollim_bot.agent import Agent

# Buttons are reconstructed from custom_id on restart; module-level ref
# is the only way to reach the agent from DynamicItem.
_agent: Agent | None = None


def init(agent: Agent) -> None:
    """Must be called before any button interaction is processed."""
    global _agent
    _agent = agent


class ActionButton(
    DynamicItem[Button], template=r"act:(?P<action>[a-z_]+):(?P<data>.+)"
):
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


async def _handle_task_done(interaction: discord.Interaction, task_id: str) -> None:
    await asyncio.to_thread(complete_task, task_id)
    await interaction.response.send_message("done ✓", ephemeral=True)


async def _handle_task_delete(interaction: discord.Interaction, task_id: str) -> None:
    await asyncio.to_thread(delete_task, task_id)
    await interaction.response.send_message("deleted", ephemeral=True)


async def _handle_event_delete(interaction: discord.Interaction, event_id: str) -> None:
    await asyncio.to_thread(delete_event, event_id)
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

    assert _agent is not None
    channel = interaction.channel
    assert isinstance(channel, discord.abc.Messageable)
    await interaction.response.defer()
    async with _agent.lock():
        await dispatch_agent_response(_agent, channel, f"[button] {prompt}")


async def _handle_dismiss(interaction: discord.Interaction, _data: str) -> None:
    await interaction.message.delete()
