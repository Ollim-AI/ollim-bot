"""Discord bot that talks to Claude Agent SDK."""

import base64
import contextlib
from typing import Literal

import discord
from discord.ext import commands
from discord.ui import Button, View

from ollim_bot import permissions
from ollim_bot.agent import Agent
from ollim_bot.agent_tools import set_channel
from ollim_bot.config import BOT_NAME, USER_NAME
from ollim_bot.embeds import fork_exit_embed
from ollim_bot.forks import (
    clear_prompted,
    enter_fork_requested,
    in_interactive_fork,
    pop_enter_fork,
    touch_activity,
)
from ollim_bot.scheduling import setup_scheduler
from ollim_bot.sessions import load_session_id
from ollim_bot.streamer import stream_to_channel
from ollim_bot.views import ActionButton
from ollim_bot.views import init as init_views

_ImageMime = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]

_MAGIC: list[tuple[bytes, _ImageMime]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
]


def _detect_image_type(data: bytes) -> _ImageMime | None:
    """Sniff image type from magic bytes -- Discord's content_type can lie."""
    for magic, mime in _MAGIC:
        if data[: len(magic)] == magic:
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _read_images(
    attachments: list[discord.Attachment],
) -> list[dict[str, str]]:
    """Detect MIME from magic bytes and base64-encode recognised image attachments."""
    images: list[dict[str, str]] = []
    for att in attachments:
        raw = await att.read()
        mime = _detect_image_type(raw)
        if mime:
            images.append(
                {
                    "media_type": mime,
                    "data": base64.b64encode(raw).decode(),
                }
            )
    return images


def create_bot() -> commands.Bot:
    """Image attachments are sniffed by magic bytes rather than Discord's unreliable content_type."""
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(
        command_prefix="!", intents=intents, status=discord.Status.online
    )
    agent = Agent()
    _ready_fired = False

    async def _dispatch(
        channel: discord.abc.Messageable,
        prompt: str,
        *,
        images: list[dict[str, str]] | None = None,
    ) -> None:
        """set_channel -> typing -> stream. Caller must hold agent.lock()."""
        set_channel(channel)
        permissions.set_channel(channel)
        await channel.typing()
        await stream_to_channel(channel, agent.stream_chat(prompt, images=images))

    async def _send_fork_enter(
        channel: discord.abc.Messageable, topic: str | None
    ) -> None:
        embed = discord.Embed(
            title="Forked Session",
            description=f"Topic: {topic}" if topic else "Open session",
            color=discord.Color.purple(),
        )
        view = View(timeout=None)
        view.add_item(
            Button(
                label="Save Context",
                style=discord.ButtonStyle.success,
                custom_id="act:fork_save:_",
            )
        )
        view.add_item(
            Button(
                label="Report",
                style=discord.ButtonStyle.primary,
                custom_id="act:fork_report:_",
            )
        )
        view.add_item(
            Button(
                label="Exit Fork",
                style=discord.ButtonStyle.danger,
                custom_id="act:fork_exit:_",
            )
        )
        await channel.send(embed=embed, view=view)

    def _fork_topic_prompt(topic: str) -> str:
        return (
            f"[fork-started] You are now inside an interactive forked session. "
            f"Your task: {topic}\n\n"
            "Work on this. When done, use save_context to promote to main, "
            "report_updates(message) to send a summary, or exit_fork to discard."
        )

    async def _check_fork_transitions(
        channel: discord.abc.Messageable,
    ) -> None:
        """Check if agent requested fork entry/exit during last response."""
        if enter_fork_requested():
            topic, timeout = pop_enter_fork()
            await agent.enter_interactive_fork(idle_timeout=timeout)
            await _send_fork_enter(channel, topic)
            if topic:
                set_channel(channel)
                permissions.set_channel(channel)
                await channel.typing()
                await stream_to_channel(
                    channel, agent.stream_chat(_fork_topic_prompt(topic))
                )
                touch_activity()
                await _check_fork_transitions(channel)
            return

        result = await agent.pop_fork_exit()
        if result:
            action, summary = result
            await channel.send(embed=fork_exit_embed(action, summary))

    @bot.tree.command(name="clear", description="Clear conversation and start fresh")
    async def slash_clear(interaction: discord.Interaction):
        await agent.clear()
        await interaction.response.send_message("conversation cleared. fresh start.")

    @bot.tree.command(name="compact", description="Compress conversation context")
    @discord.app_commands.describe(instructions="Optional focus for the summary")
    async def slash_compact(
        interaction: discord.Interaction, instructions: str | None = None
    ):
        cmd = f"/compact {instructions}" if instructions else "/compact"
        async with agent.lock():
            await interaction.response.defer(thinking=True)
            result = await agent.slash(cmd)
            await interaction.followup.send(result)

    @bot.tree.command(name="cost", description="Show token usage for this session")
    async def slash_cost(interaction: discord.Interaction):
        async with agent.lock():
            await interaction.response.defer(thinking=True)
            result = await agent.slash("/cost")
            await interaction.followup.send(result)

    @bot.tree.command(name="fork", description="Start a forked conversation")
    @discord.app_commands.describe(topic="Optional topic to start with")
    async def slash_fork(interaction: discord.Interaction, topic: str | None = None):
        if agent.in_fork:
            await interaction.response.send_message(
                "already in a fork.", ephemeral=True
            )
            return
        await interaction.response.defer()
        async with agent.lock():
            await agent.enter_interactive_fork()
            channel = interaction.channel
            assert isinstance(channel, discord.abc.Messageable)
            await _send_fork_enter(channel, topic)
            await interaction.delete_original_response()
            if topic:
                set_channel(channel)
                permissions.set_channel(channel)
                await channel.typing()
                await stream_to_channel(
                    channel, agent.stream_chat(_fork_topic_prompt(topic))
                )
                touch_activity()
                await _check_fork_transitions(channel)

    @bot.tree.command(name="model", description="Switch the AI model")
    @discord.app_commands.describe(name="Model to use")
    @discord.app_commands.choices(
        name=[
            discord.app_commands.Choice(name="opus", value="opus"),
            discord.app_commands.Choice(name="sonnet", value="sonnet"),
            discord.app_commands.Choice(name="haiku", value="haiku"),
        ]
    )
    async def slash_model(
        interaction: discord.Interaction, name: discord.app_commands.Choice[str]
    ):
        await agent.set_model(name.value)
        await interaction.response.send_message(f"switched to {name.value}.")

    @bot.event
    async def on_ready():
        nonlocal _ready_fired
        print(f"{BOT_NAME} online as {bot.user}")

        # on_ready fires again on every reconnect; init must only happen once
        if _ready_fired:
            return
        _ready_fired = True

        init_views(agent)
        bot.add_dynamic_items(ActionButton)

        synced = await bot.tree.sync()
        print(f"synced {len(synced)} slash commands")

        app_info = await bot.application_info()
        owner = app_info.owner
        if not owner:
            print("warning: no owner found; scheduler and DM disabled")
            return

        scheduler = setup_scheduler(bot, agent, owner)
        scheduler.start()
        print(f"scheduler started: {len(scheduler.get_jobs())} jobs")

        dm = await owner.create_dm()
        resumed = load_session_id() is not None
        if resumed:
            await dm.send("hey, i'm back online. i remember where we left off.")
        else:
            await dm.send(
                f"hey {USER_NAME.lower()}, {BOT_NAME} is online. what's on your plate today?"
            )

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = bot.user in message.mentions if bot.user else False

        if not is_dm and not is_mentioned:
            return

        content = (
            message.content.replace(f"<@{bot.user.id}>", "").strip()
            if bot.user
            else message.content.strip()
        )

        images = await _read_images(message.attachments)

        await message.add_reaction("\N{EYES}")

        # Interrupt so the user's new message gets a fresh response
        if agent.lock().locked():
            await agent.interrupt()

        async with agent.lock():
            await _dispatch(message.channel, content, images=images or None)
            if in_interactive_fork():
                touch_activity()
                clear_prompted()
            await _check_fork_transitions(message.channel)

        with contextlib.suppress(discord.NotFound):
            await message.remove_reaction("\N{EYES}", bot.user)

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
        if bot.user and payload.user_id == bot.user.id:
            return
        permissions.resolve_approval(payload.message_id, str(payload.emoji))

    @bot.tree.command(name="permissions", description="Set permission mode")
    @discord.app_commands.describe(mode="Permission mode to use")
    @discord.app_commands.choices(
        mode=[
            discord.app_commands.Choice(name="dontAsk", value="dontAsk"),
            discord.app_commands.Choice(name="default", value="default"),
            discord.app_commands.Choice(name="acceptEdits", value="acceptEdits"),
            discord.app_commands.Choice(
                name="bypassPermissions", value="bypassPermissions"
            ),
        ]
    )
    async def slash_permissions(
        interaction: discord.Interaction, mode: discord.app_commands.Choice[str]
    ):
        if mode.value == "dontAsk":
            permissions.set_dont_ask(True)
            await agent.set_permission_mode("default")
        else:
            permissions.set_dont_ask(False)
            await agent.set_permission_mode(mode.value)
        await interaction.response.send_message(f"permissions: {mode.value}")

    return bot
