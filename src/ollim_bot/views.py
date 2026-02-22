"""Discord UI views and persistent button handlers."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import discord
from discord.ui import Button, DynamicItem

from ollim_bot import inquiries
from ollim_bot import permissions
from ollim_bot.agent_tools import set_channel
from ollim_bot.forks import (
    append_update,
    clear_prompted,
    enter_fork_requested,
    in_interactive_fork,
    pop_enter_fork,
    touch_activity,
)
from ollim_bot.config import USER_NAME
from ollim_bot.embeds import fork_enter_embed, fork_enter_view, fork_exit_embed
from ollim_bot.google.calendar import delete_event
from ollim_bot.google.tasks import complete_task, delete_task
from ollim_bot.prompts import fork_bg_resume_prompt
from ollim_bot.sessions import lookup_fork_session
from ollim_bot.streamer import stream_to_channel

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
            "fork_save": _handle_fork_save,
            "fork_report": _handle_fork_report,
            "fork_exit": _handle_fork_exit,
        }
        handler = handlers.get(self.action)
        if handler:
            await handler(interaction, self.data)
        else:
            await interaction.response.send_message("unknown action", ephemeral=True)


async def _handle_task_done(interaction: discord.Interaction, task_id: str) -> None:
    title = await asyncio.to_thread(complete_task, task_id)
    await append_update(f'User completed task "{title}"')
    await interaction.response.send_message("done ✓", ephemeral=True)


async def _handle_task_delete(interaction: discord.Interaction, task_id: str) -> None:
    title = await asyncio.to_thread(delete_task, task_id)
    await append_update(f'User deleted task "{title}"')
    await interaction.response.send_message("deleted", ephemeral=True)


async def _handle_event_delete(interaction: discord.Interaction, event_id: str) -> None:
    summary = await asyncio.to_thread(delete_event, event_id)
    await append_update(f'User deleted calendar event "{summary}"')
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

    fork_session_id = lookup_fork_session(interaction.message.id)

    if fork_session_id and in_interactive_fork():
        await interaction.response.send_message("already in a fork.", ephemeral=True)
        return

    await interaction.response.defer()
    if _agent.lock().locked():
        await _agent.interrupt()
    async with _agent.lock():
        if fork_session_id:
            await _agent.enter_interactive_fork(resume_session_id=fork_session_id)
            await channel.send(embed=fork_enter_embed(), view=fork_enter_view())
        set_channel(channel)
        permissions.set_channel(channel)
        await channel.typing()
        message = (
            fork_bg_resume_prompt(prompt) if fork_session_id else f"[button] {prompt}"
        )
        await stream_to_channel(channel, _agent.stream_chat(message))
        if fork_session_id:
            if enter_fork_requested():
                pop_enter_fork()  # agent can't nest forks; drain stale request
            result = await _agent.pop_fork_exit()
            if result:
                action, summary = result
                await channel.send(embed=fork_exit_embed(action, summary))
            else:
                touch_activity()
                clear_prompted()


async def _handle_dismiss(interaction: discord.Interaction, _data: str) -> None:
    await interaction.message.delete()


async def _handle_fork_save(interaction: discord.Interaction, _data: str) -> None:
    from ollim_bot.forks import ForkExitAction, in_interactive_fork

    if not in_interactive_fork():
        await interaction.response.send_message("no active fork.", ephemeral=True)
        return
    assert _agent is not None
    await interaction.response.defer()
    async with _agent.lock():
        if not in_interactive_fork():
            await interaction.followup.send("fork already ended.", ephemeral=True)
            return
        await _agent.exit_interactive_fork(ForkExitAction.SAVE)
    await interaction.followup.send(
        embed=fork_exit_embed(ForkExitAction.SAVE, "context saved")
    )


async def _handle_fork_report(interaction: discord.Interaction, _data: str) -> None:
    from ollim_bot.forks import (
        ForkExitAction,
        in_interactive_fork,
        peek_pending_updates,
    )

    if not in_interactive_fork():
        await interaction.response.send_message("no active fork.", ephemeral=True)
        return
    assert _agent is not None
    channel = interaction.channel
    assert isinstance(channel, discord.abc.Messageable)
    await interaction.response.defer()
    async with _agent.lock():
        if not in_interactive_fork():
            await interaction.followup.send("fork already ended.", ephemeral=True)
            return
        updates_before = len(peek_pending_updates())
        set_channel(channel)
        permissions.set_channel(channel)
        await channel.typing()
        await stream_to_channel(
            channel,
            _agent.stream_chat(
                f"[system] {USER_NAME} clicked Report to exit this fork. "
                "You MUST call report_updates with a concise summary of "
                "what happened in this fork. Do NOT use any other tools. "
                "The fork ends immediately after your response."
            ),
        )
        updates_after = peek_pending_updates()
        new_updates = updates_after[updates_before:]
        await _agent.exit_interactive_fork(ForkExitAction.REPORT)
    summary = new_updates[-1] if new_updates else "no summary reported"
    await interaction.followup.send(
        embed=fork_exit_embed(ForkExitAction.REPORT, summary)
    )


async def _handle_fork_exit(interaction: discord.Interaction, _data: str) -> None:
    from ollim_bot.forks import ForkExitAction, in_interactive_fork

    if not in_interactive_fork():
        await interaction.response.send_message("no active fork.", ephemeral=True)
        return
    assert _agent is not None
    await interaction.response.defer()
    async with _agent.lock():
        if not in_interactive_fork():
            await interaction.followup.send("fork already ended.", ephemeral=True)
            return
        await _agent.exit_interactive_fork(ForkExitAction.EXIT)
    await interaction.followup.send(embed=fork_exit_embed(ForkExitAction.EXIT))
