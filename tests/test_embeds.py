"""Tests for embed/view builder helpers in embeds.py and prompts.py."""

import asyncio

import discord

from ollim_bot.embeds import fork_enter_embed, fork_enter_view
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


def test_fork_resume_notice_no_ts():
    from ollim_bot.prompts import fork_resume_notice

    result = fork_resume_notice(None)

    assert "[stale-fork]" in result
    assert "save_context" in result
    assert "ago)" not in result
