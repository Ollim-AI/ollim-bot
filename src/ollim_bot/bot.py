"""Discord bot that talks to Claude Agent SDK."""

import discord
from discord.ext import commands

from ollim_bot.agent import Agent
from ollim_bot.scheduler import setup_scheduler
from ollim_bot.sessions import load_session_id
from ollim_bot.streamer import stream_to_channel


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(
        command_prefix="!", intents=intents, status=discord.Status.online
    )
    agent = Agent()
    _ready_fired = False

    @bot.event
    async def on_ready():
        nonlocal _ready_fired
        print(f"ollim-bot online as {bot.user}")

        # Guard against duplicate on_ready from reconnects
        if _ready_fired:
            return
        _ready_fired = True

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

        async with message.channel.typing():
            await stream_to_channel(
                message.channel,
                agent.stream_chat(content, user_id=str(message.author.id)),
            )

    return bot
