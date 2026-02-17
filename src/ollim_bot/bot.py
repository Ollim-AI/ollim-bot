"""Discord bot that talks to Claude Agent SDK."""

import base64
import contextlib
from typing import Literal

import discord
from discord.ext import commands

from ollim_bot.agent import Agent
from ollim_bot.scheduling import setup_scheduler
from ollim_bot.sessions import load_session_id
from ollim_bot.streamer import dispatch_agent_response
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

    @bot.tree.command(name="clear", description="Clear conversation and start fresh")
    async def slash_clear(interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await agent.clear(user_id)
        await interaction.response.send_message("conversation cleared. fresh start.")

    @bot.tree.command(name="compact", description="Compress conversation context")
    @discord.app_commands.describe(instructions="Optional focus for the summary")
    async def slash_compact(
        interaction: discord.Interaction, instructions: str | None = None
    ):
        user_id = str(interaction.user.id)
        cmd = f"/compact {instructions}" if instructions else "/compact"
        async with agent.lock(user_id):
            await interaction.response.defer(thinking=True)
            result = await agent.slash(user_id, cmd)
            await interaction.followup.send(result)

    @bot.tree.command(name="cost", description="Show token usage for this session")
    async def slash_cost(interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        async with agent.lock(user_id):
            await interaction.response.defer(thinking=True)
            result = await agent.slash(user_id, "/cost")
            await interaction.followup.send(result)

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
        user_id = str(interaction.user.id)
        await agent.set_model(user_id, name.value)
        await interaction.response.send_message(f"switched to {name.value}.")

    @bot.event
    async def on_ready():
        nonlocal _ready_fired
        print(f"ollim-bot online as {bot.user}")

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
        resumed = load_session_id(str(owner.id)) is not None
        if resumed:
            await dm.send("hey, i'm back online. i remember where we left off.")
        else:
            await dm.send(
                "hey julius, ollim-bot is online. what's on your plate today?"
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
        user_id = str(message.author.id)

        await message.add_reaction("\N{EYES}")

        # Interrupt so the user's new message gets a fresh response
        if agent.lock(user_id).locked():
            await agent.interrupt(user_id)

        async with agent.lock(user_id):
            await dispatch_agent_response(
                agent, message.channel, user_id, content, images=images or None
            )

        with contextlib.suppress(discord.NotFound):
            await message.remove_reaction("\N{EYES}", bot.user)

    return bot
