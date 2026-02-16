"""Discord bot that talks to Claude Agent SDK."""

import base64
import contextlib

import discord
from discord.ext import commands

from ollim_bot.agent import Agent, ImageAttachment
from ollim_bot.discord_tools import set_channel
from ollim_bot.scheduler import setup_scheduler
from ollim_bot.sessions import load_session_id
from ollim_bot.streamer import stream_to_channel
from ollim_bot.views import ActionButton
from ollim_bot.views import init as init_views


def create_bot() -> commands.Bot:
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

        # Guard against duplicate on_ready from reconnects
        if _ready_fired:
            return
        _ready_fired = True

        # Register persistent views and set up button callbacks
        init_views(agent)
        bot.add_dynamic_items(ActionButton)

        # Sync slash commands with Discord
        synced = await bot.tree.sync()
        print(f"synced {len(synced)} slash commands")

        # Start the scheduler
        scheduler = setup_scheduler(bot, agent)
        scheduler.start()
        print(f"scheduler started: {len(scheduler.get_jobs())} jobs")

        # DM the bot owner on startup
        app_info = await bot.application_info()
        owner = app_info.owner
        if owner:
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

        # Respond to DMs or mentions in a channel
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = bot.user in message.mentions if bot.user else False

        if not is_dm and not is_mentioned:
            return

        content = (
            message.content.replace(f"<@{bot.user.id}>", "").strip()
            if bot.user
            else message.content.strip()
        )

        # Extract image attachments
        image_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        images = []
        for att in message.attachments:
            mime = (att.content_type or "").split(";")[0]
            if mime in image_types:
                data = await att.read()
                images.append(
                    ImageAttachment(
                        media_type=mime,
                        data=base64.b64encode(data).decode(),
                    )
                )

        user_id = str(message.author.id)

        # Acknowledge immediately
        await message.add_reaction("\N{EYES}")

        # Interrupt if bot is already responding to this user
        if agent.lock(user_id).locked():
            await agent.interrupt(user_id)

        async with agent.lock(user_id):
            set_channel(message.channel)
            await message.channel.typing()
            await stream_to_channel(
                message.channel,
                agent.stream_chat(content, user_id=user_id, images=images or None),
            )

        with contextlib.suppress(discord.NotFound):
            await message.remove_reaction("\N{EYES}", bot.user)

    return bot
