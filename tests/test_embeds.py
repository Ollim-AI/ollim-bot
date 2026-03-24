"""Tests for embed/view builder helpers in embeds.py and prompts.py."""

import asyncio

import discord

from ollim_bot.embeds import (
    ButtonConfig,
    EmbedConfig,
    build_embed,
    build_view,
    fork_enter_embed,
    fork_enter_view,
    save_context_embed,
    save_context_view,
)
from ollim_bot.prompts import fork_bg_resume_prompt


def _run(coro):
    # Use a fresh loop rather than asyncio.run() — asyncio.run() calls
    # set_event_loop(None) on exit, which breaks get_event_loop() in other tests.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_fork_enter_embed_no_topic():
    embed = fork_enter_embed()

    assert embed.title == "Forked Session"
    assert embed.description == "branched conversation — changes stay separate from main."


def test_fork_enter_embed_with_topic():
    embed = fork_enter_embed("morning review")

    assert embed.description == "Topic: morning review"


def test_fork_enter_view_has_three_buttons():
    # discord.ui.View.__init__ creates an asyncio.Future, requiring a running loop
    view = _run(_build_view())

    custom_ids = {item.custom_id for item in view.children}
    assert custom_ids == {"act:fork_save:_", "act:fork_report:_", "act:fork_exit:_"}


def test_fork_enter_view_button_styles():
    view = _run(_build_view())

    styles = {item.custom_id: item.style for item in view.children}
    assert styles["act:fork_save:_"] == discord.ButtonStyle.success
    assert styles["act:fork_report:_"] == discord.ButtonStyle.primary
    assert styles["act:fork_exit:_"] == discord.ButtonStyle.danger


async def _build_view() -> discord.ui.View:
    return fork_enter_view()


def test_save_context_embed():
    embed = save_context_embed()

    assert embed.title == "save context?"
    assert embed.description is not None and "replaces your main session" in embed.description
    assert embed.color == discord.Color.yellow()


def test_save_context_view_buttons():
    view = _run(_build_save_context_view())

    labels = {item.custom_id: item.label for item in view.children}
    styles = {item.custom_id: item.style for item in view.children}
    assert set(labels) == {"act:fork_save_confirm:_", "act:fork_report:_", "act:fork_save_dismiss:_"}
    assert labels["act:fork_save_confirm:_"] == "Confirm"
    assert labels["act:fork_report:_"] == "Report Instead"
    assert labels["act:fork_save_dismiss:_"] == "Dismiss"
    assert styles["act:fork_save_confirm:_"] == discord.ButtonStyle.success
    assert styles["act:fork_report:_"] == discord.ButtonStyle.primary
    assert styles["act:fork_save_dismiss:_"] == discord.ButtonStyle.secondary


async def _build_save_context_view() -> discord.ui.View:
    return save_context_view()


def test_fork_bg_resume_prompt_contains_fork_started_tag():
    result = fork_bg_resume_prompt("task completed")

    assert "[fork-started]" in result


def test_fork_bg_resume_prompt_contains_action():
    result = fork_bg_resume_prompt("snooze 1 hour")

    assert "snooze 1 hour" in result


def test_fork_bg_resume_prompt_references_bg_fork():
    result = fork_bg_resume_prompt("yes")

    assert "background fork" in result


# --- fork_resume_notice ---


def test_fork_resume_notice_includes_age():
    import time

    from ollim_bot.prompts import fork_resume_notice

    two_days_ago = time.time() - 2.5 * 86400

    result = fork_resume_notice(two_days_ago)

    assert "[stale-fork]" in result
    assert "2d ago" in result
    assert "save_context" in result
    assert "report_updates" in result


def test_build_embed_invalid_color_falls_back_to_blue():
    config = EmbedConfig(title="Test", color="magenta")  # type: ignore[arg-type]

    embed = build_embed(config)

    assert embed.color == discord.Color.blue()


def test_build_view_invalid_style_falls_back_to_secondary():
    buttons = (ButtonConfig(label="Go", action="do_thing", style="link"),)  # type: ignore[arg-type]

    async def _go():
        return build_view(buttons)

    view = _run(_go())

    assert view is not None
    btn = view.children[0]
    assert btn.style == discord.ButtonStyle.secondary


def test_fork_resume_notice_no_ts():
    from ollim_bot.prompts import fork_resume_notice

    result = fork_resume_notice(None)

    assert "[stale-fork]" in result
    assert "save_context" in result
    assert "ago)" not in result
