"""Tests for skills.py — SKILL.md generation and lifecycle."""

from ollim_bot.scheduling.reminders import Reminder
from ollim_bot.scheduling.routines import Routine
from ollim_bot.skills import (
    build_skill_md,
    cleanup_stale_skills,
    ensure_skill,
    remove_skill,
    skill_name,
)
from ollim_bot.webhook import WebhookSpec


def test_skill_name_routine():
    routine = Routine(id="abc123", message="Check tasks", cron="0 8 * * *")

    assert skill_name(routine) == "routine-abc123"


def test_skill_name_reminder():
    reminder = Reminder(id="def456", message="Take a break", run_at="2026-01-01T12:00:00")

    assert skill_name(reminder) == "reminder-def456"


def test_skill_name_webhook():
    spec = WebhookSpec(id="github-ci", message="Check.", fields={})

    assert skill_name(spec) == "webhook-github-ci"


def test_build_skill_md_routine():
    routine = Routine(
        id="abc",
        message="Review tasks and calendar.",
        cron="0 8 * * *",
        description="Morning review",
    )

    md = build_skill_md(routine)

    assert "name: routine-abc" in md
    assert "description: Morning review" in md
    assert "disable-model-invocation: true" in md
    assert "Review tasks and calendar." in md
    assert "REQUIRED SKILLS" not in md


def test_build_skill_md_routine_with_skills():
    routine = Routine(
        id="abc",
        message="Do stuff.",
        cron="0 8 * * *",
        skills=["sleep-coach", "task-review"],
        allowed_tools=["Read"],
    )

    md = build_skill_md(routine)

    assert "allowed-tools: Read" in md
    assert "Skill(sleep-coach *)" not in md  # patterns stay in BgForkConfig only
    assert "REQUIRED SKILLS:" in md
    assert "Skill(sleep-coach)" in md  # body instruction (no wildcard)
    assert "Skill(task-review)" in md


def test_build_skill_md_webhook():
    spec = WebhookSpec(id="ci", message="Check the build status.", fields={})

    md = build_skill_md(spec)

    assert "name: webhook-ci" in md
    assert "disable-model-invocation: true" in md
    assert "WEBHOOK DATA" in md
    assert "untrusted" in md
    assert "ARGUMENTS section" in md
    assert "TASK:" in md
    assert "Check the build status." in md


def test_build_skill_md_uses_name_as_description_fallback():
    routine = Routine(id="abc", message="Do stuff.", cron="0 8 * * *")

    md = build_skill_md(routine)

    assert "description: routine-abc" in md


def test_ensure_skill_creates_file(data_dir, monkeypatch):
    import ollim_bot.skills as skills_mod

    monkeypatch.setattr(skills_mod, "SKILLS_DIR", data_dir / "skills")

    routine = Routine(id="abc", message="Check tasks.", cron="0 8 * * *")
    name = ensure_skill(routine)

    assert name == "routine-abc"
    skill_file = data_dir / "skills" / "routine-abc" / "SKILL.md"
    assert skill_file.exists()
    assert "name: routine-abc" in skill_file.read_text()


def test_ensure_skill_updates_on_change(data_dir, monkeypatch):
    import ollim_bot.skills as skills_mod

    monkeypatch.setattr(skills_mod, "SKILLS_DIR", data_dir / "skills")

    routine_v1 = Routine(id="abc", message="Version 1.", cron="0 8 * * *")
    ensure_skill(routine_v1)

    routine_v2 = Routine(id="abc", message="Version 2.", cron="0 8 * * *")
    ensure_skill(routine_v2)

    skill_file = data_dir / "skills" / "routine-abc" / "SKILL.md"
    content = skill_file.read_text()
    assert "Version 2." in content
    assert "Version 1." not in content


def test_remove_skill(data_dir, monkeypatch):
    import ollim_bot.skills as skills_mod

    monkeypatch.setattr(skills_mod, "SKILLS_DIR", data_dir / "skills")

    routine = Routine(id="abc", message="Check.", cron="0 8 * * *")
    ensure_skill(routine)
    assert (data_dir / "skills" / "routine-abc").is_dir()

    remove_skill("routine-abc")

    assert not (data_dir / "skills" / "routine-abc").exists()


def test_remove_skill_nonexistent(data_dir, monkeypatch):
    import ollim_bot.skills as skills_mod

    monkeypatch.setattr(skills_mod, "SKILLS_DIR", data_dir / "skills")

    remove_skill("routine-nonexistent")  # should not raise


def test_cleanup_stale_skills(data_dir, monkeypatch):
    import ollim_bot.skills as skills_mod

    monkeypatch.setattr(skills_mod, "SKILLS_DIR", data_dir / "skills")

    r1 = Routine(id="aaa", message="Keep.", cron="0 8 * * *")
    r2 = Routine(id="bbb", message="Remove.", cron="0 8 * * *")
    ensure_skill(r1)
    ensure_skill(r2)

    cleanup_stale_skills({"routine-aaa"})

    assert (data_dir / "skills" / "routine-aaa").is_dir()
    assert not (data_dir / "skills" / "routine-bbb").exists()


def test_install_bundled_skills_improve_routine(data_dir, monkeypatch):
    import ollim_bot.skills as skills_mod

    monkeypatch.setattr(skills_mod, "SKILLS_DIR", data_dir / "skills")

    skills_mod.install_bundled_skills()

    skill_file = data_dir / "skills" / "improve-routine" / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text(encoding="utf-8")
    assert content.startswith("---"), "Bundled skill should start with YAML frontmatter"

    # Overwrite with sentinel to verify idempotency
    skill_file.write_text("custom content", encoding="utf-8")
    skills_mod.install_bundled_skills()
    assert skill_file.read_text(encoding="utf-8") == "custom content", (
        "install_bundled_skills must not overwrite existing files"
    )


def test_cleanup_ignores_non_generated_skills(data_dir, monkeypatch):
    import ollim_bot.skills as skills_mod

    monkeypatch.setattr(skills_mod, "SKILLS_DIR", data_dir / "skills")

    # Create a user skill that should not be touched
    user_skill = data_dir / "skills" / "sleep-coach"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text("---\nname: sleep-coach\n---\nUser skill.\n")

    cleanup_stale_skills(set())

    assert (data_dir / "skills" / "sleep-coach").is_dir()
