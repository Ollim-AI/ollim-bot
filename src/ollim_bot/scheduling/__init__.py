# ollim-bot
# Copyright (C) 2025-2026 Julius Frost
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Scheduling: routines, reminders, and the APScheduler integration."""

from ollim_bot.scheduling.reminders import (
    Reminder,
    append_reminder,
    list_reminders,
    remove_reminder,
)
from ollim_bot.scheduling.routines import (
    Routine,
    append_routine,
    list_routines,
    remove_routine,
)
from ollim_bot.scheduling.scheduler import setup_scheduler

__all__ = [
    "Reminder",
    "Routine",
    "append_reminder",
    "append_routine",
    "list_reminders",
    "list_routines",
    "remove_reminder",
    "remove_routine",
    "setup_scheduler",
]
