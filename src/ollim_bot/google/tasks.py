"""CLI handler for `ollim-bot tasks` subcommand."""

import argparse
import sys
from typing import Any

from ollim_bot.google.auth import get_service


def _get_tasks_service() -> Any:
    return get_service("tasks", "v1")


def run_tasks_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot tasks")
    sub = parser.add_subparsers(dest="action")

    list_p = sub.add_parser("list", help="List tasks")
    list_p.add_argument("--all", action="store_true", help="Include completed")

    add_p = sub.add_parser("add", help="Add a task")
    add_p.add_argument("title", help="Task title")
    add_p.add_argument("--due", help="Due date YYYY-MM-DD")
    add_p.add_argument("--notes", help="Task notes")

    done_p = sub.add_parser("done", help="Mark task as completed")
    done_p.add_argument("id", help="Task ID")

    del_p = sub.add_parser("delete", help="Delete a task")
    del_p.add_argument("id", help="Task ID")

    upd_p = sub.add_parser("update", help="Update a task")
    upd_p.add_argument("id", help="Task ID")
    upd_p.add_argument("--title", help="New title")
    upd_p.add_argument("--due", help="New due date YYYY-MM-DD")
    upd_p.add_argument("--notes", help="New notes")

    args = parser.parse_args(argv)

    if args.action == "list":
        _handle_list(args)
    elif args.action == "add":
        _handle_add(args)
    elif args.action == "done":
        _handle_done(args.id)
    elif args.action == "delete":
        _handle_delete(args.id)
    elif args.action == "update":
        _handle_update(args)
    else:
        parser.print_help()
        sys.exit(1)


def _handle_list(args: argparse.Namespace) -> None:
    service = _get_tasks_service()
    tasks: list[dict] = []
    page_token = None

    while True:
        result = (
            service.tasks()
            .list(
                tasklist="@default",
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
        due = t.get("due", "")[:10] if t.get("due") else "(no due)"
        status = "[x]" if t.get("status") == "completed" else "[ ]"
        print(f"  {t['id']}  {due:12s}  {status}  {t.get('title', '')}")


def _handle_add(args: argparse.Namespace) -> None:
    body: dict = {"title": args.title}
    if args.due:
        body["due"] = f"{args.due}T00:00:00.000Z"
    if args.notes:
        body["notes"] = args.notes

    service = _get_tasks_service()
    task = service.tasks().insert(tasklist="@default", body=body).execute()
    due = args.due or "(no due)"
    print(f"added {task['id']}: {due} -- {args.title}")


def complete_task(task_id: str) -> None:
    _get_tasks_service().tasks().patch(
        tasklist="@default",
        task=task_id,
        body={"status": "completed"},
    ).execute()


def delete_task(task_id: str) -> None:
    _get_tasks_service().tasks().delete(tasklist="@default", task=task_id).execute()


def _handle_done(task_id: str) -> None:
    complete_task(task_id)
    print(f"completed {task_id}")


def _handle_delete(task_id: str) -> None:
    delete_task(task_id)
    print(f"deleted {task_id}")


def _handle_update(args: argparse.Namespace) -> None:
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
        tasklist="@default",
        task=args.id,
        body=body,
    ).execute()
    print(f"updated {args.id}")
