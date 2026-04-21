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
"""Discord UI views and persistent button handlers."""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING, Any, cast

import discord
from discord.ui import Button, DynamicItem, Item
from googleapiclient.errors import HttpError

from ollim_bot import inquiries, runtime_config
from ollim_bot.config import USER_NAME
from ollim_bot.embeds import fork_enter_embed, fork_enter_view, fork_exit_embed
from ollim_bot.fork_state import (
    clear_prompted,
    enter_fork_requested,
    in_interactive_fork,
    pop_enter_fork,
    touch_activity,
)
from ollim_bot.forks import append_update
from ollim_bot.google.calendar import delete_event
from ollim_bot.google.tasks import complete_task, delete_task
from ollim_bot.prompts import fork_bg_resume_prompt, fork_resume_notice
from ollim_bot.sessions import (
    cancel_message_collector,
    flush_message_collector,
    load_session_id,
    lookup_fork_session,
    start_message_collector,
    track_fork_message,
    track_message,
)
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


class ActionButton(DynamicItem[Button], template=r"act:(?P<action>[a-z_]+):(?P<data>.+)"):
    def __init__(self, button: Button):
        super().__init__(button)
        self.action: str = ""
        self.data: str = ""

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: Item[Any],
        match: re.Match[str],
        /,
    ) -> ActionButton:
        inst = cls(cast(Button, item))
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
            "fork_save_confirm": _handle_fork_save_confirm,
            "fork_save_dismiss": _handle_dismiss,
            "fork_report": _handle_fork_report,
            "fork_exit": _handle_fork_exit,
        }
        handler = handlers.get(self.action)
        if handler:
            await handler(interaction, self.data)
        else:
            await interaction.response.send_message("unknown action", ephemeral=True)


def _split_task_data(data: str) -> tuple[str, str]:
    parts = data.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return runtime_config.load().google_task_list, data


async def _handle_task_done(interaction: discord.Interaction, data: str) -> None:
    task_list, task_id = _split_task_data(data)
    try:
        title = await asyncio.to_thread(complete_task, task_id, task_list)
    except HttpError as e:
        await interaction.response.send_message(f"failed: {e.reason}", ephemeral=True)
        return
    await append_update(f'User completed task "{title}"')
    await interaction.response.send_message("done ✓", ephemeral=True)


async def _handle_task_delete(interaction: discord.Interaction, data: str) -> None:
    task_list, task_id = _split_task_data(data)
    try:
        title = await asyncio.to_thread(delete_task, task_id, task_list)
    except HttpError as e:
        await interaction.response.send_message(f"failed: {e.reason}", ephemeral=True)
        return
    await append_update(f'User deleted task "{title}"')
    await interaction.response.send_message("deleted", ephemeral=True)


async def _handle_event_delete(interaction: discord.Interaction, data: str) -> None:
    parts = data.split("/", 1)
    if len(parts) == 2:
        calendar_id, event_id = parts
    else:
        calendar_id, event_id = "primary", data
    try:
        summary = await asyncio.to_thread(delete_event, event_id, calendar_id)
    except HttpError as e:
        await interaction.response.send_message(f"failed: {e.reason}", ephemeral=True)
        return
    await append_update(f'User deleted calendar event "{summary}"')
    await interaction.response.send_message("deleted", ephemeral=True)


async def _handle_agent_inquiry(interaction: discord.Interaction, inquiry_id: str) -> None:
    assert _agent is not None
    channel = interaction.channel
    assert isinstance(channel, discord.abc.Messageable)

    assert interaction.message is not None
    fork_lookup = lookup_fork_session(interaction.message.id)
    fork_session_id = fork_lookup.session_id

    if fork_session_id and in_interactive_fork():
        await interaction.response.send_message("already in a fork.", ephemeral=True)
        return

    prompt = inquiries.pop(inquiry_id)
    if not prompt:
        await interaction.response.send_message("this option has expired — ask again to revisit.", ephemeral=True)
        return

    await interaction.response.defer()
    if _agent.lock().locked():
        await _agent.interrupt()
    async with _agent.lock():
        if fork_session_id:
            await _agent.enter_interactive_fork(resume_session_id=fork_session_id)
            start_message_collector()
            msg = await channel.send(embed=fork_enter_embed(), view=fork_enter_view())
            track_message(msg.id)
        await channel.typing()
        message = fork_bg_resume_prompt(prompt) if fork_session_id else f"[button] {prompt}"
        if fork_session_id:
            message = f"{message}\n\n{fork_resume_notice(fork_lookup.ts)}"
        await stream_to_channel(channel, _agent.stream_chat(message))
        if fork_session_id:
            sid = _agent.fork_session_id
            if sid:
                flush_message_collector(sid, load_session_id())
            else:
                cancel_message_collector()
        if enter_fork_requested():
            pop_enter_fork()  # drain; fork entry requires the bot.py loop
        fork_sid = _agent.fork_session_id
        parent_sid = load_session_id()
        result = await _agent.pop_fork_exit()
        if result:
            action, summary = result
            msg = await channel.send(embed=fork_exit_embed(action, summary))
            if fork_sid:
                track_fork_message(msg.id, fork_sid, parent_sid)
        elif fork_session_id:
            touch_activity()
            clear_prompted()


async def _handle_dismiss(interaction: discord.Interaction, _data: str) -> None:
    assert interaction.message is not None
    await interaction.response.defer()
    with contextlib.suppress(discord.NotFound):
        await interaction.message.delete()


async def _handle_fork_save_confirm(interaction: discord.Interaction, _data: str) -> None:
    """Confirm button on the save-context embed — delete embed, then save."""
    await _do_fork_save(interaction, delete_trigger=True)


async def _handle_fork_save(interaction: discord.Interaction, _data: str) -> None:
    """Save Context button on the fork-enter embed (user-initiated shortcut)."""
    await _do_fork_save(interaction, delete_trigger=False)


async def _do_fork_save(interaction: discord.Interaction, *, delete_trigger: bool) -> None:
    from ollim_bot.fork_state import ForkExitAction, in_interactive_fork

    if not in_interactive_fork():
        await interaction.response.send_message("no active fork.", ephemeral=True)
        return
    assert _agent is not None
    await interaction.response.defer()
    if delete_trigger:
        with contextlib.suppress(discord.HTTPException):
            assert interaction.message is not None
            await interaction.message.delete()
    async with _agent.lock():
        if not in_interactive_fork():
            await interaction.followup.send("fork already ended.", ephemeral=True)
            return
        fork_sid = _agent.fork_session_id
        parent_sid = load_session_id()
        saved = await _agent.exit_interactive_fork(ForkExitAction.SAVE)
    summary = "context saved" if saved else "fork discarded (no session to save)"
    action = ForkExitAction.SAVE if saved else ForkExitAction.EXIT
    msg = await interaction.followup.send(embed=fork_exit_embed(action, summary), wait=True)
    if fork_sid:
        track_fork_message(msg.id, fork_sid, parent_sid)


async def _handle_fork_report(interaction: discord.Interaction, _data: str) -> None:
    from ollim_bot.fork_state import ForkExitAction, in_interactive_fork
    from ollim_bot.forks import peek_pending_updates

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
        seen_ts = {u.ts for u in peek_pending_updates()}
        await channel.typing()
        await stream_to_channel(
            channel,
            _agent.stream_chat(
                f"[system] {USER_NAME} clicked Report to exit this fork. "
                "You MUST call report_updates with a concise summary of "
                "what happened in this fork — name findings and sources. "
                "Do NOT use any other tools. "
                "The fork ends immediately after your response."
            ),
        )
        new_updates = [u for u in peek_pending_updates() if u.ts not in seen_ts]
        fork_sid = _agent.fork_session_id
        parent_sid = load_session_id()
        await _agent.exit_interactive_fork(ForkExitAction.REPORT)
    summary = new_updates[-1].message if new_updates else "no summary reported"
    msg = await interaction.followup.send(embed=fork_exit_embed(ForkExitAction.REPORT, summary), wait=True)
    if fork_sid:
        track_fork_message(msg.id, fork_sid, parent_sid)


async def _handle_fork_exit(interaction: discord.Interaction, _data: str) -> None:
    from ollim_bot.fork_state import ForkExitAction, in_interactive_fork

    if not in_interactive_fork():
        await interaction.response.send_message("no active fork.", ephemeral=True)
        return
    assert _agent is not None
    await interaction.response.defer()
    async with _agent.lock():
        if not in_interactive_fork():
            await interaction.followup.send("fork already ended.", ephemeral=True)
            return
        fork_sid = _agent.fork_session_id
        parent_sid = load_session_id()
        await _agent.exit_interactive_fork(ForkExitAction.EXIT)
    msg = await interaction.followup.send(embed=fork_exit_embed(ForkExitAction.EXIT), wait=True)
    if fork_sid:
        track_fork_message(msg.id, fork_sid, parent_sid)
