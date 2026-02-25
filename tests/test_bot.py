"""Tests for bot.py — owner identity guard."""

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
