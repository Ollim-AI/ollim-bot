"""CLI diagnostic checks for the routine execution pipeline.

Covers every layer a routine passes through: timezone, data files, cron
registration, tool policy, Claude CLI auth, state files, and env vars.
Run via ``ollim-bot doctor``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ollim_bot.config import TZ
from ollim_bot.scheduling.reminders import Reminder, list_reminders
from ollim_bot.scheduling.routines import Routine, list_routines


@dataclass(frozen=True, slots=True)
class CheckResult:
    status: Literal["PASS", "WARN", "FAIL"]
    label: str
    message: str


# ---------------------------------------------------------------------------
# Layer 1: Timezone & APScheduler compatibility
# ---------------------------------------------------------------------------


def check_timezone() -> list[CheckResult]:
    results: list[CheckResult] = []
    tz_name = str(TZ)
    results.append(CheckResult("PASS", "timezone", tz_name))

    if sys.platform == "win32":
        try:
            import tzlocal  # noqa: F401

            results.append(CheckResult("PASS", "tzlocal", "importable"))
        except ImportError:
            results.append(CheckResult("FAIL", "tzlocal", "not installed — timezone detection may fail"))

    from apscheduler.triggers.cron import CronTrigger

    try:
        CronTrigger(hour="0", timezone=tz_name)
        results.append(CheckResult("PASS", "APScheduler timezone", "accepted"))
    except (ValueError, KeyError) as exc:
        results.append(CheckResult("FAIL", "APScheduler timezone", f"rejected: {exc}"))

    return results


# ---------------------------------------------------------------------------
# Layer 2+3: Routine files, cron validation, next fire time
# ---------------------------------------------------------------------------


def _count_md_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return len(list(directory.glob("*.md")))


def check_routines() -> list[CheckResult]:
    from ollim_bot.scheduling.preamble import _convert_dow, _routine_next_fire
    from ollim_bot.scheduling.routines import ROUTINES_DIR

    results: list[CheckResult] = []
    file_count = _count_md_files(ROUTINES_DIR)
    routines = list_routines()

    skipped = file_count - len(routines)
    if skipped > 0:
        results.append(
            CheckResult(
                "FAIL",
                f"routine files ({skipped} corrupt)",
                f"{file_count} files found, {len(routines)} parsed — {skipped} skipped (check logs)",
            )
        )
    elif file_count == 0:
        results.append(CheckResult("WARN", "routines", "no routine files found"))
    else:
        results.append(CheckResult("PASS", "routine files", f"{file_count} loaded"))

    now = datetime.now(TZ)
    for routine in routines:
        nxt = _routine_next_fire(routine, now)

        if nxt is None:
            # Distinguish malformed cron from legitimately no upcoming fire
            parts = routine.cron.split()
            if len(parts) != 5:
                results.append(
                    CheckResult(
                        "FAIL", routine.id, f"invalid cron '{routine.cron}': expected 5 fields, got {len(parts)}"
                    )
                )
            else:
                # Try constructing CronTrigger to surface the actual error
                from apscheduler.triggers.cron import CronTrigger

                try:
                    CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=_convert_dow(parts[4]),
                        timezone=str(TZ),
                    )
                    results.append(CheckResult("WARN", routine.id, f"no upcoming fire time (cron: {routine.cron})"))
                except (ValueError, KeyError, IndexError) as exc:
                    results.append(CheckResult("FAIL", routine.id, f"invalid cron '{routine.cron}': {exc}"))
        else:
            local_time = nxt.strftime("%I:%M %p").lstrip("0")
            delta = nxt - now
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes = remainder // 60
            results.append(
                CheckResult(
                    "PASS",
                    routine.id,
                    f"next fire {local_time} (in {hours}h {minutes:02d}m)",
                )
            )

    return results


def check_reminders() -> list[CheckResult]:
    from ollim_bot.scheduling.reminders import REMINDERS_DIR

    results: list[CheckResult] = []
    file_count = _count_md_files(REMINDERS_DIR)
    reminders = list_reminders()

    skipped = file_count - len(reminders)
    if skipped > 0:
        results.append(
            CheckResult(
                "FAIL",
                f"reminder files ({skipped} corrupt)",
                f"{file_count} files found, {len(reminders)} parsed — {skipped} skipped",
            )
        )
    elif file_count == 0:
        results.append(CheckResult("PASS", "reminders", "none pending"))
    else:
        results.append(CheckResult("PASS", "reminder files", f"{len(reminders)} loaded"))

    for reminder in reminders:
        try:
            datetime.fromisoformat(reminder.run_at)
            results.append(CheckResult("PASS", reminder.id, f"run_at: {reminder.run_at}"))
        except ValueError as exc:
            results.append(CheckResult("FAIL", reminder.id, f"invalid run_at '{reminder.run_at}': {exc}"))

    return results


# ---------------------------------------------------------------------------
# Layer 2: Data directory
# ---------------------------------------------------------------------------


def check_data_dir() -> list[CheckResult]:
    from ollim_bot.storage import DATA_DIR

    results: list[CheckResult] = []

    if not DATA_DIR.is_dir():
        results.append(CheckResult("FAIL", "DATA_DIR", f"missing: {DATA_DIR}"))
        return results
    results.append(CheckResult("PASS", "DATA_DIR", str(DATA_DIR)))

    try:
        probe = DATA_DIR / ".diagnose_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        results.append(CheckResult("PASS", "DATA_DIR writable", "yes"))
    except OSError as exc:
        results.append(CheckResult("FAIL", "DATA_DIR writable", str(exc)))

    git_dir = DATA_DIR / ".git"
    if git_dir.is_dir():
        results.append(CheckResult("PASS", "DATA_DIR git", "initialized"))
    else:
        results.append(CheckResult("WARN", "DATA_DIR git", "not initialized — auto-commit disabled"))

    return results


# ---------------------------------------------------------------------------
# Layer 4: Tool policy
# ---------------------------------------------------------------------------


def check_tool_policy(
    routines: list[Routine] | None = None,
    reminders: list[Reminder] | None = None,
) -> list[CheckResult]:
    from ollim_bot.tool_policy import validate_dispatch

    results: list[CheckResult] = []
    items: list[Routine | Reminder] = [
        *[r for r in (routines or list_routines()) if r.background],
        *[r for r in (reminders or list_reminders()) if r.background],
    ]
    if not items:
        results.append(CheckResult("PASS", "tool policy", "no background items to validate"))
        return results

    for item in items:
        tools = item.allowed_tools
        if validate_dispatch(tools, source=item.id):
            results.append(CheckResult("PASS", item.id, "tool policy valid"))
        else:
            results.append(CheckResult("FAIL", item.id, "tool policy invalid — job will be skipped"))

    return results


# ---------------------------------------------------------------------------
# Layer 5: Claude CLI & auth
# ---------------------------------------------------------------------------


def check_claude_cli() -> list[CheckResult]:
    try:
        from ollim_bot.auth import _find_bundled_cli

        cli_path = _find_bundled_cli()
        return [CheckResult("PASS", "Claude CLI", cli_path)]
    except (SystemExit, ImportError) as exc:
        return [CheckResult("FAIL", "Claude CLI", f"not found: {exc}")]


def check_claude_auth() -> list[CheckResult]:
    try:
        from ollim_bot.auth import is_authenticated

        if is_authenticated():
            return [CheckResult("PASS", "Claude auth", "logged in")]
        return [CheckResult("FAIL", "Claude auth", "not logged in — run 'ollim-bot auth login'")]
    except (SystemExit, FileNotFoundError) as exc:
        return [CheckResult("FAIL", "Claude auth", f"check failed: {exc}")]


# ---------------------------------------------------------------------------
# Layer 6: State files
# ---------------------------------------------------------------------------

_STATE_FILES = [
    "pending_updates.json",
    "config.json",
    "ping_budget.json",
    "fork_messages.json",
    "inquiries.json",
]


def check_state_files() -> list[CheckResult]:
    from ollim_bot.storage import STATE_DIR

    results: list[CheckResult] = []
    for name in _STATE_FILES:
        path = STATE_DIR / name
        try:
            json.loads(path.read_text(encoding="utf-8"))
            results.append(CheckResult("PASS", name, "valid JSON"))
        except FileNotFoundError:
            results.append(CheckResult("PASS", name, "not present (will use defaults)"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            results.append(CheckResult("FAIL", name, f"corrupt: {exc}"))

    return results


# ---------------------------------------------------------------------------
# Layer 7: Environment variables
# ---------------------------------------------------------------------------

_REQUIRED_VARS = ["DISCORD_TOKEN", "OLLIM_USER_NAME", "OLLIM_BOT_NAME"]
_OPTIONAL_VARS = ["OLLIM_TIMEZONE", "WEBHOOK_PORT", "WEBHOOK_SECRET"]


def check_env_vars() -> list[CheckResult]:
    results: list[CheckResult] = []
    for var in _REQUIRED_VARS:
        if os.environ.get(var):
            results.append(CheckResult("PASS", var, "set"))
        else:
            results.append(CheckResult("FAIL", var, "missing"))

    for var in _OPTIONAL_VARS:
        val = os.environ.get(var)
        if val:
            results.append(CheckResult("PASS", var, "set"))

    return results


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------


def _run_all_checks() -> list[tuple[str, list[CheckResult]]]:
    # Cache routine/reminder lists to avoid re-reading files for tool policy check
    cached_routines = list_routines()
    cached_reminders = list_reminders()
    return [
        ("ENVIRONMENT", check_env_vars()),
        ("DATA DIRECTORY", check_data_dir()),
        ("TIMEZONE & SCHEDULING", check_timezone()),
        ("ROUTINES", check_routines()),
        ("REMINDERS", check_reminders()),
        ("TOOL POLICY", check_tool_policy(cached_routines, cached_reminders)),
        ("STATE FILES", check_state_files()),
        ("CLAUDE CLI", check_claude_cli()),
        ("CLAUDE AUTH", check_claude_auth()),
    ]


def _print_results(sections: list[tuple[str, list[CheckResult]]]) -> int:
    total_pass = total_warn = total_fail = 0

    for title, results in sections:
        print(f"\n{title}")
        for r in results:
            print(f"  {r.status}  {r.label}: {r.message}")
            if r.status == "PASS":
                total_pass += 1
            elif r.status == "WARN":
                total_warn += 1
            else:
                total_fail += 1

    print(f"\nSUMMARY: {total_pass} passed, {total_warn} warnings, {total_fail} failures")
    return total_fail


def run_doctor_command(args: list[str]) -> None:
    from dotenv import load_dotenv

    from ollim_bot.storage import PROJECT_DIR

    load_dotenv(PROJECT_DIR / ".env")

    sections = _run_all_checks()
    failures = _print_results(sections)
    raise SystemExit(1 if failures else 0)
