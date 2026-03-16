"""Tests for diagnose.py — CLI diagnostic checks."""

import ollim_bot.forks as forks_mod
import ollim_bot.inquiries as inquiries_mod
import ollim_bot.runtime_config as runtime_config_mod
import ollim_bot.scheduling.routines as routines_mod
import ollim_bot.sessions as sessions_mod
import ollim_bot.storage as storage_mod
from ollim_bot.doctor import (
    check_data_dir,
    check_env_vars,
    check_reminders,
    check_routines,
    check_state_files,
    check_timezone,
)
from ollim_bot.scheduling.reminders import Reminder, append_reminder
from ollim_bot.scheduling.routines import Routine, append_routine
from ollim_bot.storage import safe_json_load

# --- safe_json_load ---


def test_safe_json_load_returns_default_when_missing(tmp_path):
    path = tmp_path / "nope.json"

    result = safe_json_load(path, [])

    assert result == []


def test_safe_json_load_returns_parsed_json(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text('{"a": 1}', encoding="utf-8")

    result = safe_json_load(path)

    assert result == {"a": 1}


def test_safe_json_load_returns_default_on_corrupt(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{invalid json", encoding="utf-8")

    result = safe_json_load(path, {"fallback": True})

    assert result == {"fallback": True}


def test_safe_json_load_returns_default_on_encoding_error(tmp_path):
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe{}")

    result = safe_json_load(path, [])

    assert result == []


# --- check_timezone ---


def test_check_timezone_passes():
    results = check_timezone()

    statuses = {r.label: r.status for r in results}
    assert statuses["timezone"] == "PASS"
    assert statuses["APScheduler timezone"] == "PASS"


# --- check_data_dir ---


def test_check_data_dir_passes(data_dir):
    data_dir.mkdir(exist_ok=True)

    results = check_data_dir()

    statuses = {r.label: r.status for r in results}
    assert statuses["DATA_DIR"] == "PASS"
    assert statuses["DATA_DIR writable"] == "PASS"


def test_check_data_dir_warns_no_git(data_dir):
    data_dir.mkdir(exist_ok=True)

    results = check_data_dir()

    statuses = {r.label: r.status for r in results}
    assert statuses["DATA_DIR git"] == "WARN"


def test_check_data_dir_passes_with_git(data_dir):
    (data_dir / ".git").mkdir(parents=True)

    results = check_data_dir()

    statuses = {r.label: r.status for r in results}
    assert statuses["DATA_DIR git"] == "PASS"


# --- check_routines ---


def test_check_routines_warns_no_files(data_dir):
    results = check_routines()

    assert any(r.status == "WARN" and "no routine files" in r.message for r in results)


def test_check_routines_passes_valid_routine(data_dir):
    routine = Routine.new(message="morning check", cron="30 8 * * *", background=True)
    append_routine(routine)

    results = check_routines()

    statuses = {r.label: r.status for r in results}
    assert statuses["routine files"] == "PASS"
    assert statuses[routine.id] == "PASS"
    assert "next fire" in next(r.message for r in results if r.label == routine.id)


def test_check_routines_detects_corrupt_file(data_dir):
    routine = Routine.new(message="good routine", cron="0 9 * * *", background=True)
    append_routine(routine)

    corrupt_path = routines_mod.ROUTINES_DIR / "bad-routine.md"
    corrupt_path.write_text("not valid yaml at all", encoding="utf-8")

    results = check_routines()

    assert any(r.status == "FAIL" and "corrupt" in r.label for r in results)


def test_check_routines_detects_invalid_cron(data_dir):
    routines_dir = routines_mod.ROUTINES_DIR
    routines_dir.mkdir(parents=True, exist_ok=True)
    (routines_dir / "bad-cron.md").write_text(
        '---\nid: "bad-cron"\ncron: "99 99 * * *"\n---\ntest\n',
        encoding="utf-8",
    )

    results = check_routines()

    assert any(r.status == "FAIL" and "invalid cron" in r.message for r in results)


# --- check_reminders ---


def test_check_reminders_passes_none_pending(data_dir):
    results = check_reminders()

    assert any(r.status == "PASS" and "none pending" in r.message for r in results)


def test_check_reminders_passes_valid(data_dir):
    reminder = Reminder.new(message="take break", delay_minutes=60)
    append_reminder(reminder)

    results = check_reminders()

    statuses = {r.label: r.status for r in results}
    assert statuses["reminder files"] == "PASS"
    assert statuses[reminder.id] == "PASS"


# --- check_state_files ---


def test_check_state_files_passes_when_missing(data_dir):
    results = check_state_files()

    assert all(r.status == "PASS" for r in results)


def test_check_state_files_passes_valid_json(data_dir):
    state_dir = storage_mod.STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "config.json").write_text("{}", encoding="utf-8")

    results = check_state_files()

    config_result = next(r for r in results if r.label == "config.json")
    assert config_result.status == "PASS"


def test_check_state_files_detects_corrupt(data_dir):
    state_dir = storage_mod.STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "config.json").write_text("{broken", encoding="utf-8")

    results = check_state_files()

    config_result = next(r for r in results if r.label == "config.json")
    assert config_result.status == "FAIL"
    assert "corrupt" in config_result.message


# --- check_env_vars ---


def test_check_env_vars_passes_when_set():
    results = check_env_vars()

    statuses = {r.label: r.status for r in results}
    assert statuses["OLLIM_USER_NAME"] == "PASS"
    assert statuses["OLLIM_BOT_NAME"] == "PASS"


def test_check_env_vars_fails_missing(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)

    results = check_env_vars()

    token_result = next(r for r in results if r.label == "DISCORD_TOKEN")
    assert token_result.status == "FAIL"


# --- JSON corruption recovery in callers ---


def test_corrupt_pending_updates_recovers(data_dir):
    updates_file = forks_mod._UPDATES_FILE
    updates_file.parent.mkdir(parents=True, exist_ok=True)
    updates_file.write_text("{bad json", encoding="utf-8")

    result = forks_mod.peek_pending_updates()

    assert result == []


def test_corrupt_config_returns_defaults(data_dir):
    cfg_file = runtime_config_mod.CONFIG_FILE
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text("{bad", encoding="utf-8")

    result = runtime_config_mod.load()

    assert result == runtime_config_mod.RuntimeConfig()


def test_corrupt_inquiries_returns_empty(data_dir):
    inq_file = inquiries_mod.INQUIRIES_FILE
    inq_file.parent.mkdir(parents=True, exist_ok=True)
    inq_file.write_text("not json", encoding="utf-8")

    result = inquiries_mod._read()

    assert result == {}


def test_corrupt_fork_messages_returns_empty(data_dir):
    fm_file = sessions_mod.FORK_MESSAGES_FILE
    fm_file.parent.mkdir(parents=True, exist_ok=True)
    fm_file.write_text("{{{", encoding="utf-8")

    result = sessions_mod._read_all_fork_messages()

    assert result == []


# --- Scheduler self-notification (corrupt files → pending_updates) ---


def _glob_md(directory):
    return sorted(directory.glob("*.md")) if directory.is_dir() else []


def test_corrupt_routine_file_surfaces_to_pending_updates(data_dir):
    import asyncio

    import ollim_bot.scheduling.scheduler as scheduler_mod
    from ollim_bot.scheduling.scheduler import _check_corrupt_files

    scheduler_mod._reported_problems.clear()

    routines_dir = routines_mod.ROUTINES_DIR
    routines_dir.mkdir(parents=True, exist_ok=True)

    good = Routine.new(message="good routine", cron="0 9 * * *")
    append_routine(good)
    (routines_dir / "broken.md").write_text("not valid", encoding="utf-8")

    _check_corrupt_files(1, "routine", _glob_md(routines_dir))
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))

    updates = forks_mod.peek_pending_updates()
    assert len(updates) == 1
    assert "corrupt routine" in updates[0].message
    assert "broken.md" in updates[0].message


def test_corrupt_file_notification_deduplicates(data_dir):
    import asyncio

    import ollim_bot.scheduling.scheduler as scheduler_mod
    from ollim_bot.scheduling.scheduler import _check_corrupt_files

    scheduler_mod._reported_problems.clear()

    routines_dir = routines_mod.ROUTINES_DIR
    routines_dir.mkdir(parents=True, exist_ok=True)
    (routines_dir / "broken.md").write_text("not valid", encoding="utf-8")

    files = _glob_md(routines_dir)
    _check_corrupt_files(0, "routine", files)
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    _check_corrupt_files(0, "routine", files)
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))

    updates = forks_mod.peek_pending_updates()
    assert len(updates) == 1


def test_corrupt_file_notification_clears_on_fix(data_dir):
    import ollim_bot.scheduling.scheduler as scheduler_mod
    from ollim_bot.scheduling.scheduler import _check_corrupt_files

    scheduler_mod._reported_problems.clear()

    routines_dir = routines_mod.ROUTINES_DIR
    routines_dir.mkdir(parents=True, exist_ok=True)
    (routines_dir / "broken.md").write_text("not valid", encoding="utf-8")

    _check_corrupt_files(0, "routine", _glob_md(routines_dir))
    assert "corrupt_routine_files" in scheduler_mod._reported_problems

    (routines_dir / "broken.md").unlink()
    _check_corrupt_files(0, "routine", _glob_md(routines_dir))
    assert "corrupt_routine_files" not in scheduler_mod._reported_problems
