"""CLI handler for `ollim-bot routine` subcommand."""

import argparse
import sys

from ollim_bot.scheduling.routines import (
    Routine,
    append_routine,
    list_routines,
    remove_routine,
)


def _summary(r: Routine) -> str:
    return r.description or r.message


def _fmt_schedule(r: Routine) -> str:
    sched = f"cron '{r.cron}'"
    if r.background:
        parts = ["bg"]
        if r.isolated:
            parts.append("isolated")
        tag = f"[{','.join(parts)}]"
        sched = f"{tag} {sched}"
    if r.model:
        sched += f"  (model: {r.model})"
    if not r.thinking:
        sched += "  (no-thinking)"
    return sched


def run_routine_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot routine")
    sub = parser.add_subparsers(dest="action")

    add_p = sub.add_parser("add", help="Add a recurring routine")
    add_p.add_argument("--message", "-m", required=True, help="Agent prompt")
    add_p.add_argument("--cron", required=True, help='5-field cron (e.g. "0 9 * * 1-5")')
    add_p.add_argument("--description", "-d", default="", help="Short summary for list")
    add_p.add_argument("--background", action="store_true", help="Silent mode")
    add_p.add_argument("--model", default=None, help="Model override (bg only)")
    add_p.add_argument(
        "--no-thinking",
        action="store_true",
        help="Disable extended thinking (bg only)",
    )
    add_p.add_argument("--isolated", action="store_true", help="Fresh context (bg only)")
    add_p.add_argument(
        "--update-main-session",
        default="on_ping",
        choices=["always", "on_ping", "freely", "blocked"],
        help="When to report to main session (bg only)",
    )
    add_p.add_argument(
        "--no-ping",
        action="store_true",
        help="Disable ping_user/discord_embed (bg only)",
    )

    sub.add_parser("list", help="Show all routines")

    cancel_p = sub.add_parser("cancel", help="Cancel a routine by ID")
    cancel_p.add_argument("id", help="Routine ID")

    args = parser.parse_args(argv)

    if args.action == "add":
        _handle_add(args)
    elif args.action == "list":
        _handle_list()
    elif args.action == "cancel":
        _handle_cancel(args.id)
    else:
        parser.print_help()
        sys.exit(1)


def _handle_add(args: argparse.Namespace) -> None:
    if len(args.cron.split()) != 5:
        print("error: cron must be 5 fields (minute hour day month weekday)")
        sys.exit(1)

    routine = Routine.new(
        message=args.message,
        cron=args.cron,
        description=args.description,
        background=args.background,
        model=args.model,
        thinking=not args.no_thinking,
        isolated=args.isolated,
        update_main_session=args.update_main_session,
        allow_ping=not args.no_ping,
    )
    append_routine(routine)
    print(f"scheduled {routine.id}: {_fmt_schedule(routine)} -- {_summary(routine)}")


def _handle_list() -> None:
    routines = list_routines()
    if not routines:
        print("no routines")
        return
    for r in routines:
        print(f"  {r.id}  {_fmt_schedule(r):24s}  {_summary(r)}")


def _handle_cancel(routine_id: str) -> None:
    if remove_routine(routine_id):
        print(f"cancelled {routine_id}")
    else:
        print(f"routine {routine_id} not found")
        sys.exit(1)
