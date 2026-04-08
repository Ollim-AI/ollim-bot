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
"""CLI handler for `ollim-bot tasks` subcommand."""

import argparse
import sys
from typing import Any

from ollim_bot import runtime_config
from ollim_bot.google.auth import get_service


def _get_tasks_service() -> Any:
    return get_service("tasks", "v1")


def _default_task_list() -> str:
    return runtime_config.load().google_task_list


def run_tasks_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot tasks")
    sub = parser.add_subparsers(dest="action")

    list_p = sub.add_parser("list", help="List tasks")
    list_p.add_argument("--all", action="store_true", help="Include completed")
    list_p.add_argument("--list", dest="task_list", help="Task list ID (default: configured)")

    show_p = sub.add_parser("show", help="Show task details")
    show_p.add_argument("id", help="Task ID")
    show_p.add_argument("--list", dest="task_list", help="Task list ID (default: configured)")

    add_p = sub.add_parser("add", help="Add a task")
    add_p.add_argument("title", help="Task title")
    add_p.add_argument("--due", help="Due date YYYY-MM-DD")
    add_p.add_argument("--notes", help="Task notes")
    add_p.add_argument("--list", dest="task_list", help="Task list ID (default: configured)")

    done_p = sub.add_parser("done", help="Mark task as completed")
    done_p.add_argument("id", help="Task ID")
    done_p.add_argument("--list", dest="task_list", help="Task list ID (default: configured)")

    del_p = sub.add_parser("delete", help="Delete a task")
    del_p.add_argument("id", help="Task ID")
    del_p.add_argument("--list", dest="task_list", help="Task list ID (default: configured)")

    upd_p = sub.add_parser("update", help="Update a task")
    upd_p.add_argument("id", help="Task ID")
    upd_p.add_argument("--title", help="New title")
    upd_p.add_argument("--due", help="New due date YYYY-MM-DD")
    upd_p.add_argument("--notes", help="New notes")
    upd_p.add_argument("--list", dest="task_list", help="Task list ID (default: configured)")

    args = parser.parse_args(argv)
    tl = args.task_list or _default_task_list()

    if args.action == "list":
        _handle_list(args, task_list=tl)
    elif args.action == "show":
        _handle_show(args.id, task_list=tl)
    elif args.action == "add":
        _handle_add(args, task_list=tl)
    elif args.action == "done":
        _handle_done(args.id, task_list=tl)
    elif args.action == "delete":
        _handle_delete(args.id, task_list=tl)
    elif args.action == "update":
        _handle_update(args, task_list=tl)
    else:
        parser.print_help()
        sys.exit(1)


def _fmt_due(due: str | None) -> str:
    return due[:10] if due else "(no due)"


def _handle_list(args: argparse.Namespace, task_list: str = "@default") -> None:
    service = _get_tasks_service()
    tasks: list[dict] = []
    page_token = None

    while True:
        result = (
            service.tasks()
            .list(
                tasklist=task_list,
                showCompleted=args.all,
                showHidden=args.all,
                pageToken=page_token,
            )
            .execute()
        )
        tasks.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    if not tasks:
        print("no tasks")
        return

    for t in tasks:
        due = _fmt_due(t.get("due"))
        status = "[x]" if t.get("status") == "completed" else "[ ]"
        notes_marker = " [+]" if t.get("notes") else ""
        print(f"  {t['id']}  {due:12s}  {status}  {t.get('title', '')}{notes_marker}")


def _handle_show(task_id: str, task_list: str = "@default") -> None:
    service = _get_tasks_service()
    t = service.tasks().get(tasklist=task_list, task=task_id).execute()

    status = "completed" if t.get("status") == "completed" else "needs action"
    due = _fmt_due(t.get("due"))

    print(f"title:     {t.get('title', '(no title)')}")
    print(f"status:    {status}")
    print(f"due:       {due}")
    if t.get("notes"):
        indented = t["notes"].replace("\n", "\n           ")
        print(f"notes:     {indented}")
    print(f"id:        {t['id']}")


def _handle_add(args: argparse.Namespace, task_list: str = "@default") -> None:
    body: dict = {"title": args.title}
    if args.due:
        body["due"] = f"{args.due}T00:00:00.000Z"
    if args.notes:
        body["notes"] = args.notes

    service = _get_tasks_service()
    task = service.tasks().insert(tasklist=task_list, body=body).execute()
    due = args.due or "(no due)"
    print(f"added {task['id']}: {due} -- {args.title}")


def complete_task(task_id: str, task_list: str = "@default") -> str:
    """Mark a task as completed and return its title."""
    result = (
        _get_tasks_service()
        .tasks()
        .patch(
            tasklist=task_list,
            task=task_id,
            body={"status": "completed"},
        )
        .execute()
    )
    return result.get("title", task_id)


def delete_task(task_id: str, task_list: str = "@default") -> str:
    """Delete a task and return its title."""
    service = _get_tasks_service()
    task = service.tasks().get(tasklist=task_list, task=task_id).execute()
    title = task.get("title", task_id)
    service.tasks().delete(tasklist=task_list, task=task_id).execute()
    return title


def _handle_done(task_id: str, task_list: str = "@default") -> None:
    complete_task(task_id, task_list=task_list)
    print(f"completed {task_id}")


def _handle_delete(task_id: str, task_list: str = "@default") -> None:
    delete_task(task_id, task_list=task_list)
    print(f"deleted {task_id}")


def _handle_update(args: argparse.Namespace, task_list: str = "@default") -> None:
    body: dict = {}
    if args.title is not None:
        body["title"] = args.title
    if args.due is not None:
        body["due"] = f"{args.due}T00:00:00.000Z"
    if args.notes is not None:
        body["notes"] = args.notes
    if not body:
        print("error: provide at least one of --title, --due, --notes")
        sys.exit(1)

    service = _get_tasks_service()
    service.tasks().patch(
        tasklist=task_list,
        task=args.id,
        body=body,
    ).execute()
    print(f"updated {args.id}")
