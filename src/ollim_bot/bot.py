"""Discord bot that talks to Claude Agent SDK."""

import discord
from discord.ext import commands

from ollim_bot.agent import Agent


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    agent = Agent()

    @bot.event
    async def on_ready():
        print(f"ollim-bot online as {bot.user}")

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
            response = await agent.chat(content, user_id=str(message.author.id))

        # Discord has a 2000 char limit
        for i in range(0, len(response), 2000):
            await message.channel.send(response[i : i + 2000])

    return bot
