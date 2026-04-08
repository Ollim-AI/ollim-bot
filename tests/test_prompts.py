"""Tests for prompts module — system prompt builder and fork prompt helpers."""

import ollim_bot.prompts as prompts_mod

# -- build_system_prompt -----------------------------------------------------------


def test_build_system_prompt_with_profile(monkeypatch):
    """Profile text is prepended when load_profile returns content."""
    monkeypatch.setattr(prompts_mod, "load_profile", lambda: "# My Profile\nI am a test profile.")
    result = prompts_mod.build_system_prompt()
    assert result.startswith("# My Profile")
    assert "I am a test profile." in result


def test_build_system_prompt_without_profile(monkeypatch):
    """Operational text only when load_profile returns empty string."""
    monkeypatch.setattr(prompts_mod, "load_profile", lambda: "")
    result = prompts_mod.build_system_prompt()
    assert not result.startswith("\n")
    assert "Google Tasks" in result


def test_build_system_prompt_profile_none_treated_as_falsy(monkeypatch):
    """None from load_profile treated same as empty — operational text only."""
    monkeypatch.setattr(prompts_mod, "load_profile", lambda: None)
    result = prompts_mod.build_system_prompt()
    assert "Google Tasks" in result
    assert result == prompts_mod.build_system_prompt()


def test_build_system_prompt_contains_section_headers(monkeypatch):
    """All expected section headers appear in the operational text."""
    monkeypatch.setattr(prompts_mod, "load_profile", lambda: "")
    result = prompts_mod.build_system_prompt()
    for header in (
        "Google Tasks",
        "Google Calendar",
        "Routines & Reminders",
        "Discord Embeds",
        "Interactive Forks",
        "Background Session Management",
        "Webhooks",
        "Skills",
    ):
        assert header in result, f"Missing section header: {header}"


def test_build_system_prompt_contains_user_name(monkeypatch):
    """USER_NAME is substituted into operational text."""
    monkeypatch.setattr(prompts_mod, "load_profile", lambda: "")
    result = prompts_mod.build_system_prompt()
    assert prompts_mod.USER_NAME in result


def test_build_system_prompt_profile_separated_from_operational(monkeypatch):
    """Profile and operational text are separated by blank lines."""
    monkeypatch.setattr(prompts_mod, "load_profile", lambda: "PROFILE_SENTINEL")
    result = prompts_mod.build_system_prompt()
    assert "PROFILE_SENTINEL\n\n" in result


# -- fork_bg_resume_prompt ---------------------------------------------------------


def test_fork_bg_resume_prompt_contains_inquiry():
    """The inquiry prompt text appears in the output."""
    result = prompts_mod.fork_bg_resume_prompt("What about X?")
    assert "What about X?" in result


def test_fork_bg_resume_prompt_contains_user_name():
    """USER_NAME is referenced in the fork resume prompt."""
    result = prompts_mod.fork_bg_resume_prompt("test")
    assert prompts_mod.USER_NAME in result


def test_fork_bg_resume_prompt_mentions_interactive_fork():
    """Prompt clarifies this is an interactive fork."""
    result = prompts_mod.fork_bg_resume_prompt("test")
    assert "interactive fork" in result


def test_fork_bg_resume_prompt_mentions_background_origin():
    """Prompt mentions the background fork origin."""
    result = prompts_mod.fork_bg_resume_prompt("test")
    assert "background fork" in result


# -- google integration text ---


def test_system_prompt_mentions_configurable_calendars(monkeypatch):
    """Multi-calendar config instructions appear in system prompt."""
    monkeypatch.setattr(prompts_mod, "load_profile", lambda: "")
    result = prompts_mod.build_system_prompt()
    assert "google_calendars" in result
    assert "ollim-bot cal calendars" in result


def test_system_prompt_mentions_configurable_task_list(monkeypatch):
    """Task list config instruction appears in system prompt."""
    monkeypatch.setattr(prompts_mod, "load_profile", lambda: "")
    result = prompts_mod.build_system_prompt()
    assert "google_task_list" in result
