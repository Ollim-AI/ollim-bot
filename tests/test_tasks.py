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
"""Tests for google/tasks.py — configurable task list."""

import io
import sys
from unittest.mock import MagicMock

import pytest

from ollim_bot.google import tasks as tasks_mod


@pytest.fixture()
def mock_service(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(tasks_mod, "_get_tasks_service", lambda: svc)
    return svc


@pytest.fixture()
def default_task_list(monkeypatch):
    monkeypatch.setattr(tasks_mod, "_default_task_list", lambda: "@default")


def _capture(fn, *args, **kwargs):
    old = sys.stdout
    sys.stdout = buf = io.StringIO()
    fn(*args, **kwargs)
    sys.stdout = old
    return buf.getvalue()


# --- --list flag flows through ---


class TestTaskListFlag:
    def test_list_uses_config_default(self, mock_service, default_task_list):
        mock_service.tasks().list().execute.return_value = {"items": []}
        _capture(tasks_mod.run_tasks_command, ["list"])
        mock_service.tasks().list.assert_called_with(
            tasklist="@default",
            showCompleted=False,
            showHidden=False,
            pageToken=None,
        )

    def test_list_uses_explicit_flag(self, mock_service, default_task_list):
        mock_service.tasks().list().execute.return_value = {"items": []}
        _capture(tasks_mod.run_tasks_command, ["list", "--list", "MyTasks"])
        mock_service.tasks().list.assert_called_with(
            tasklist="MyTasks",
            showCompleted=False,
            showHidden=False,
            pageToken=None,
        )


# --- complete_task / delete_task with task_list ---


class TestCompleteTask:
    def test_default_task_list(self, mock_service):
        mock_service.tasks().patch().execute.return_value = {"title": "Buy milk"}
        title = tasks_mod.complete_task("tid")
        assert title == "Buy milk"
        mock_service.tasks().patch.assert_called_with(
            tasklist="@default",
            task="tid",
            body={"status": "completed"},
        )

    def test_explicit_task_list(self, mock_service):
        mock_service.tasks().patch().execute.return_value = {"title": "Buy milk"}
        tasks_mod.complete_task("tid", task_list="work")
        mock_service.tasks().patch.assert_called_with(
            tasklist="work",
            task="tid",
            body={"status": "completed"},
        )


class TestDeleteTask:
    def test_default_task_list(self, mock_service):
        mock_service.tasks().get().execute.return_value = {"title": "Buy milk"}
        title = tasks_mod.delete_task("tid")
        assert title == "Buy milk"
        mock_service.tasks().get.assert_called_with(tasklist="@default", task="tid")
        mock_service.tasks().delete.assert_called_with(tasklist="@default", task="tid")

    def test_explicit_task_list(self, mock_service):
        mock_service.tasks().get().execute.return_value = {"title": "Buy milk"}
        tasks_mod.delete_task("tid", task_list="work")
        mock_service.tasks().get.assert_called_with(tasklist="work", task="tid")
        mock_service.tasks().delete.assert_called_with(tasklist="work", task="tid")
