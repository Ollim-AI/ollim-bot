"""Discord bot that talks to Claude Agent SDK."""

import base64
import contextlib
import logging
from typing import Literal, cast

import discord
from claude_agent_sdk import CLIConnectionError
from discord import app_commands
from discord.ext import commands

from ollim_bot import permissions, ping_budget, runtime_config, webhook
from ollim_bot.agent import Agent
from ollim_bot.agent_context import ModelName
from ollim_bot.channel import init_channel
from ollim_bot.config import BOT_NAME, USER_NAME
from ollim_bot.embeds import fork_enter_embed, fork_enter_view, fork_exit_embed
from ollim_bot.fork_state import (
    ForkExitAction,
    clear_prompted,
    enter_fork_requested,
    in_interactive_fork,
    pop_enter_fork,
    touch_activity,
)
from ollim_bot.scheduling import setup_scheduler
from ollim_bot.sessions import load_session_id, lookup_fork_session
from ollim_bot.streamer import stream_to_channel
from ollim_bot.views import ActionButton
from ollim_bot.views import init as init_views

log = logging.getLogger(__name__)

_owner_id: int | None = None


def get_owner_id() -> int | None:
    return _owner_id


def is_owner(user_id: int) -> bool:
    """Check if user is the bot owner. Allows all when owner not yet resolved."""
    return _owner_id is None or user_id == _owner_id


def _owner_check(interaction: discord.Interaction) -> bool:
    return is_owner(interaction.user.id)


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


_MAX_QUOTE_LEN = 500


def _quote_message(msg: discord.Message) -> str:
    """Extract quotable text from a message's content or embeds."""
    if msg.content:
        text = msg.content
    elif msg.embeds:
        embed = msg.embeds[0]
        parts: list[str] = []
        if embed.title:
            parts.append(f"**{embed.title}**")
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(f"**{field.name}**: {field.value}")
        text = "\n".join(parts)
    else:
        return ""
    if len(text) > _MAX_QUOTE_LEN:
        text = text[:_MAX_QUOTE_LEN] + "..."
    return "\n".join(f"> {line}" for line in text.splitlines())


def create_bot() -> commands.Bot:
    """Image attachments are sniffed by magic bytes rather than Discord's unreliable content_type."""
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(
        command_prefix="!",
        intents=intents,
        status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.watching, name="your DMs"),
    )
    agent = Agent()
    _ready_fired = False

    async def _dispatch(
        channel: discord.abc.Messageable,
        prompt: str,
        *,
        images: list[dict[str, str]] | None = None,
    ) -> None:
        """typing -> stream (stream_to_channel sets channel). Caller must hold agent.lock()."""
        await channel.typing()
        await stream_to_channel(channel, agent.stream_chat(prompt, images=images))

    async def _send_fork_enter(channel: discord.abc.Messageable, topic: str | None) -> None:
        await channel.send(embed=fork_enter_embed(topic), view=fork_enter_view())

    def _fork_topic_prompt(topic: str) -> str:
        return (
            f"[fork-started] You are now inside an interactive forked session. "
            f"Topic: {topic}\n\n"
            f"Respond to the topic, then wait for {USER_NAME} to reply before "
            "considering exit — they started this fork to have a conversation."
        )

    _FORK_NO_TOPIC_PROMPT = (
        f"[fork-started] You are now inside an interactive forked session. "
        f"No topic was given — {USER_NAME} will lead. Wait for their message."
    )

    _FORK_REPLY_PREFIX = (
        "[fork-started] You are now inside an interactive forked session (resumed from a background fork reply)."
    )

    async def _check_fork_transitions(
        channel: discord.abc.Messageable,
    ) -> None:
        """Check if agent requested fork entry/exit during last response."""
        if enter_fork_requested():
            topic, timeout = pop_enter_fork()
            if agent.in_fork:
                return
            await agent.enter_interactive_fork(idle_timeout=timeout)
            await _send_fork_enter(channel, topic)
            prompt = _fork_topic_prompt(topic) if topic else _FORK_NO_TOPIC_PROMPT
            await channel.typing()
            await stream_to_channel(channel, agent.stream_chat(prompt))
            touch_activity()
            await _check_fork_transitions(channel)
            return

        result = await agent.pop_fork_exit()
        if result:
            action, summary = result
            await channel.send(embed=fork_exit_embed(action, summary))

    @bot.tree.command(name="clear", description="Clear conversation and start fresh")
    @discord.app_commands.check(_owner_check)
    async def slash_clear(interaction: discord.Interaction):
        was_in_fork = agent.in_fork
        await agent.clear()
        if was_in_fork:
            channel = interaction.channel
            assert isinstance(channel, discord.abc.Messageable)
            await channel.send(embed=fork_exit_embed(ForkExitAction.EXIT, None))
            await interaction.response.send_message("fork discarded, conversation cleared.", ephemeral=True)
        else:
            await interaction.response.send_message("conversation cleared. fresh start.", ephemeral=True)

    @bot.tree.command(name="compact", description="Compress conversation context")
    @discord.app_commands.describe(instructions="Optional focus for the summary")
    @discord.app_commands.check(_owner_check)
    async def slash_compact(interaction: discord.Interaction, instructions: str | None = None):
        await interaction.response.defer(thinking=True)
        async with agent.lock():
            result = await agent.compact(instructions)
        await interaction.followup.send(result)

    @bot.tree.command(name="cost", description="Show token usage for this session")
    @discord.app_commands.check(_owner_check)
    async def slash_cost(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        async with agent.lock():
            result = await agent.slash("/cost")
            await interaction.followup.send(result)

    @bot.tree.command(name="fork", description="Start a forked conversation")
    @discord.app_commands.describe(topic="Optional topic to start with")
    @discord.app_commands.check(_owner_check)
    async def slash_fork(interaction: discord.Interaction, topic: str | None = None):
        if agent.in_fork:
            await interaction.response.send_message("already in a fork.", ephemeral=True)
            return
        await interaction.response.defer()
        async with agent.lock():
            await agent.enter_interactive_fork()
            channel = interaction.channel
            assert isinstance(channel, discord.abc.Messageable)
            await _send_fork_enter(channel, topic)
            await interaction.delete_original_response()
            prompt = _fork_topic_prompt(topic) if topic else _FORK_NO_TOPIC_PROMPT
            await channel.typing()
            await stream_to_channel(channel, agent.stream_chat(prompt))
            touch_activity()
            await _check_fork_transitions(channel)

    @bot.tree.command(name="model", description="Switch the AI model")
    @discord.app_commands.describe(name="Model to use")
    @discord.app_commands.check(_owner_check)
    @discord.app_commands.choices(
        name=[
            discord.app_commands.Choice(name="opus", value="opus"),
            discord.app_commands.Choice(name="sonnet", value="sonnet"),
            discord.app_commands.Choice(name="haiku", value="haiku"),
        ]
    )
    async def slash_model(interaction: discord.Interaction, name: discord.app_commands.Choice[str]):
        if agent.in_fork:
            await interaction.response.send_message("exit fork first.", ephemeral=True)
            return
        await agent.set_model(cast(ModelName, name.value))
        await interaction.response.send_message(f"switched to {name.value}.")

    @bot.tree.command(name="thinking", description="Toggle extended thinking")
    @discord.app_commands.describe(enabled="Turn thinking on or off")
    @discord.app_commands.check(_owner_check)
    @discord.app_commands.choices(
        enabled=[
            discord.app_commands.Choice(name="on", value="on"),
            discord.app_commands.Choice(name="off", value="off"),
        ]
    )
    async def slash_thinking(interaction: discord.Interaction, enabled: discord.app_commands.Choice[str]):
        if agent.in_fork:
            await interaction.response.send_message("exit fork first.", ephemeral=True)
            return
        await agent.set_thinking(enabled.value == "on")
        await interaction.response.send_message(f"thinking: {enabled.value}.")

    @bot.event
    async def on_ready():
        nonlocal _ready_fired
        print(f"{BOT_NAME} online as {bot.user}")

        # on_ready fires again on every reconnect; init must only happen once
        if _ready_fired:
            return
        _ready_fired = True

        cfg = runtime_config.load()
        permissions.set_dont_ask(cfg.permission_mode == "dontAsk")

        init_views(agent)
        bot.add_dynamic_items(ActionButton)

        bot.tree.allowed_installs = app_commands.AppInstallationType(guild=False, user=True)
        bot.tree.allowed_contexts = app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=True)

        synced = await bot.tree.sync()
        print(f"synced {len(synced)} slash commands")

        global _owner_id
        app_info = await bot.application_info()
        owner = app_info.owner
        if not owner:
            print("warning: no owner found; scheduler and DM disabled")
            return

        _owner_id = owner.id

        scheduler = setup_scheduler(bot, agent, owner)
        scheduler.start()
        print(f"scheduler started: {len(scheduler.get_jobs())} jobs")

        await webhook.start(agent, owner)

        dm = await owner.create_dm()
        init_channel(dm)
        resumed = load_session_id() is not None
        if resumed:
            await dm.send("hey, i'm back. picking up where we left off.")
        else:
            await dm.send(f"hey {USER_NAME.lower()}, {BOT_NAME} is online. what's on your plate today?")

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        if not is_owner(message.author.id):
            return

        if not isinstance(message.channel, discord.DMChannel):
            return

        content = message.content.strip()

        await message.add_reaction("\N{EYES}")

        images = await _read_images(message.attachments)

        # Reply handling: fork-from-reply or quote context
        # Gap: lookup_fork_session returns None for both "never tracked" and "expired
        # after 7 days" — we can't distinguish them without sessions.py exposing
        # expired-entry detection. A TTL-expired reply silently degrades to quoted
        # context with no signal (#5).
        ref = message.reference
        fork_session_id: str | None = None
        if ref and ref.message_id:
            fork_session_id = lookup_fork_session(ref.message_id)
            if fork_session_id and agent.in_fork:
                fork_session_id = None
                await message.channel.send("-# already in a fork — reply added as context instead.")
            if not fork_session_id:
                try:
                    replied = ref.resolved or await message.channel.fetch_message(ref.message_id)
                    if isinstance(replied, discord.Message):
                        if quoted := _quote_message(replied):
                            content = f"{quoted}\n\n{content}"
                except discord.NotFound:
                    pass

        # Interrupt so the user's new message gets a fresh response.
        # Skip during compaction: interrupt kills the post-compaction response
        # (dead zone), and the new message would trigger a redundant compaction.
        if agent.lock().locked() and not agent.is_compacting:
            await agent.interrupt()

        error_msg: str | None = None
        try:
            async with agent.lock():
                if fork_session_id:
                    await agent.enter_interactive_fork(resume_session_id=fork_session_id)
                    await _send_fork_enter(message.channel, None)
                    content = f"{_FORK_REPLY_PREFIX}\n\n{content}"
                await _dispatch(message.channel, content, images=images or None)
                if in_interactive_fork():
                    touch_activity()
                    clear_prompted()
                await _check_fork_transitions(message.channel)
        except CLIConnectionError as e:
            log.error("CLIConnectionError in on_message: %s", e)
            error_msg = "lost connection — try again."
        finally:
            if bot.user:
                with contextlib.suppress(discord.NotFound):
                    await message.remove_reaction("\N{EYES}", bot.user)
            if error_msg is not None:
                await message.channel.send(error_msg)

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
        if bot.user and payload.user_id == bot.user.id:
            return
        if not is_owner(payload.user_id):
            return
        permissions.resolve_approval(payload.message_id, str(payload.emoji))

    @bot.tree.command(name="interrupt", description="Stop the current response")
    @discord.app_commands.check(_owner_check)
    async def slash_interrupt(interaction: discord.Interaction):
        if agent.lock().locked():
            await agent.interrupt()
        await interaction.response.defer()
        await interaction.delete_original_response()

    @bot.tree.command(name="permissions", description="Set permission mode")
    @discord.app_commands.describe(mode="Permission mode to use")
    @discord.app_commands.check(_owner_check)
    @discord.app_commands.choices(
        mode=[
            discord.app_commands.Choice(name="dontAsk", value="dontAsk"),
            discord.app_commands.Choice(name="default", value="default"),
            discord.app_commands.Choice(name="acceptEdits", value="acceptEdits"),
            discord.app_commands.Choice(name="bypassPermissions", value="bypassPermissions"),
        ]
    )
    async def slash_permissions(interaction: discord.Interaction, mode: discord.app_commands.Choice[str]):
        if mode.value == "dontAsk":
            permissions.set_dont_ask(True)
            await agent.set_permission_mode("default")
        else:
            permissions.set_dont_ask(False)
            await agent.set_permission_mode(mode.value)
        await interaction.response.send_message(f"permissions: {mode.value}.")

    @bot.tree.command(name="ping-budget", description="View or set ping budget")
    @discord.app_commands.describe(
        capacity="Max pings (omit to view current)",
        refill_rate="Minutes per refill (default 90)",
    )
    @discord.app_commands.check(_owner_check)
    async def slash_ping_budget(
        interaction: discord.Interaction,
        capacity: int | None = None,
        refill_rate: int | None = None,
    ):
        if capacity is not None:
            ping_budget.set_capacity(capacity)
        if refill_rate is not None:
            ping_budget.set_refill_rate(refill_rate)
        if capacity is not None or refill_rate is not None:
            status = ping_budget.get_status()
            await interaction.response.send_message(f"ping budget updated: {status}.")
        else:
            status = ping_budget.get_full_status()
            await interaction.response.send_message(f"ping budget: {status}.")

    @bot.tree.command(name="config", description="View or set runtime configuration")
    @discord.app_commands.describe(
        key="Config key to view or set",
        value="New value (omit to view current)",
    )
    @discord.app_commands.choices(
        key=[
            discord.app_commands.Choice(name="model.main", value="model_main"),
            discord.app_commands.Choice(name="model.fork", value="model_fork"),
            discord.app_commands.Choice(name="thinking.main", value="thinking_main"),
            discord.app_commands.Choice(name="thinking.fork", value="thinking_fork"),
            discord.app_commands.Choice(name="max_thinking_tokens", value="max_thinking_tokens"),
            discord.app_commands.Choice(name="bg_fork_timeout", value="bg_fork_timeout"),
            discord.app_commands.Choice(name="fork_idle_timeout", value="fork_idle_timeout"),
            discord.app_commands.Choice(name="permission_mode", value="permission_mode"),
        ]
    )
    @discord.app_commands.check(_owner_check)
    async def slash_config(
        interaction: discord.Interaction,
        key: discord.app_commands.Choice[str] | None = None,
        value: str | None = None,
    ):
        if key is None:
            await interaction.response.send_message(runtime_config.format_all())
            return
        if value is None:
            await interaction.response.send_message(runtime_config.format_one(key.value))
            return
        try:
            runtime_config.set_value(key.value, value)
        except ValueError as exc:
            await interaction.response.send_message(f"{key.name}: {exc}", ephemeral=True)
            return
        await agent.apply_config(key.value)
        await interaction.response.send_message(runtime_config.format_one(key.value))

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, discord.app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message("not authorized", ephemeral=True)
            return
        log.error("Slash command error: %s", error)
        if not interaction.response.is_done():
            await interaction.response.send_message("something went wrong.", ephemeral=True)
        raise error

    return bot
