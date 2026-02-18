#!/usr/bin/env python3
"""One-time migration: convert reminders.jsonl and routines.jsonl to markdown files."""

from ollim_bot.scheduling.reminders import REMINDERS_DIR, Reminder, append_reminder
from ollim_bot.scheduling.routines import ROUTINES_DIR, Routine, append_routine
from ollim_bot.storage import DATA_DIR, read_jsonl

REMINDERS_JSONL = DATA_DIR / "reminders.jsonl"
ROUTINES_JSONL = DATA_DIR / "routines.jsonl"


def migrate() -> None:
    reminders = read_jsonl(REMINDERS_JSONL, Reminder)
    for r in reminders:
        append_reminder(r)
        print(f"  migrated reminder {r.id}: {r.message[:60]}")
    print(f"Migrated {len(reminders)} reminders to {REMINDERS_DIR}")

    routines = read_jsonl(ROUTINES_JSONL, Routine)
    for r in routines:
        append_routine(r)
        print(f"  migrated routine {r.id}: {r.message[:60]}")
    print(f"Migrated {len(routines)} routines to {ROUTINES_DIR}")


if __name__ == "__main__":
    migrate()
