"""Tests for bot.py — owner guard and DM-only enforcement."""

import discord
import pytest

import ollim_bot.bot as bot_mod


@pytest.fixture(autouse=True)
def _reset_owner_id():
    """Ensure _owner_id is reset after each test."""
    yield
    bot_mod._owner_id = None


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeInteraction:
    def __init__(self, user_id: int):
        self.user = _FakeUser(user_id)


def test_message_from_non_owner_is_ignored():
    bot_mod._owner_id = 42

    assert bot_mod.is_owner(99) is False


def test_message_from_owner_is_processed():
    bot_mod._owner_id = 42

    assert bot_mod.is_owner(42) is True


def test_owner_unset_accepts_all():
    bot_mod._owner_id = None

    assert bot_mod.is_owner(99) is True


def test_slash_command_from_non_owner_returns_error():
    bot_mod._owner_id = 42

    assert bot_mod._owner_check(_FakeInteraction(user_id=99)) is False


def test_slash_command_from_owner_accepted():
    bot_mod._owner_id = 42

    assert bot_mod._owner_check(_FakeInteraction(user_id=42)) is True


# --- DM-only enforcement ---


class _Processed(Exception):
    """Sentinel raised when on_message passes all guards and starts processing."""


class _FakeAuthor:
    def __init__(self, user_id: int, *, bot: bool = False):
        self.id = user_id
        self.bot = bot


class _GuildChannel:
    """Non-DM channel — on_message should reject messages here."""


class _FakeDMChannel(discord.DMChannel):
    """Minimal DMChannel subclass that passes isinstance checks."""

    def __init__(self) -> None:
        pass  # skip discord internals


class _FakeMessage:
    """Message that raises _Processed on add_reaction (first side effect after guards)."""

    def __init__(self, channel: object, author: _FakeAuthor) -> None:
        self.channel = channel
        self.author = author
        self.content = "hello"
        self.attachments: list[object] = []
        self.reference = None


    async def add_reaction(self, emoji: str) -> None:
        raise _Processed("passed DM guard")


@pytest.mark.asyncio
async def test_non_dm_message_ignored():
    bot_mod._owner_id = 42
    bot = bot_mod.create_bot()

    msg = _FakeMessage(channel=_GuildChannel(), author=_FakeAuthor(42))
    # Should return silently — never reaches add_reaction
    await bot.on_message(msg)


@pytest.mark.asyncio
async def test_dm_message_processed():
    bot_mod._owner_id = 42
    bot = bot_mod.create_bot()

    msg = _FakeMessage(channel=_FakeDMChannel(), author=_FakeAuthor(42))
    # Should pass DM guard and reach add_reaction, raising _Processed
    with pytest.raises(_Processed):
        await bot.on_message(msg)
