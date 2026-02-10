"""CLI handler for `ollim-bot schedule` subcommand."""

import argparse
import sys

from ollim_bot.wakeups import Wakeup, append_wakeup, list_wakeups, remove_wakeup


def run_schedule_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="ollim-bot schedule")
    sub = parser.add_subparsers(dest="action")

    # -- add --
    add_p = sub.add_parser("add", help="Schedule a new wakeup")
    add_p.add_argument("--message", "-m", required=True, help="Wakeup message/context")
    add_p.add_argument("--delay", type=int, help="One-shot: fire in N minutes")
    add_p.add_argument("--cron", help='Recurring: 5-field cron (e.g. "0 9 * * 1-5")')
    add_p.add_argument("--every", type=int, help="Interval: fire every N minutes")

    # -- list --
    sub.add_parser("list", help="Show pending wakeups")

    # -- cancel --
    cancel_p = sub.add_parser("cancel", help="Cancel a wakeup by ID")
    cancel_p.add_argument("id", help="Wakeup ID to cancel")

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
    if not (args.delay or args.cron or args.every):
        print("error: provide --delay, --cron, or --every")
        sys.exit(1)

    wakeup = Wakeup.new(
        message=args.message,
        delay_minutes=args.delay,
        cron=args.cron,
        interval_minutes=args.every,
    )
    append_wakeup(wakeup)

    schedule = (
        f"in {wakeup.delay_minutes}min" if wakeup.delay_minutes
        else f"cron '{wakeup.cron}'" if wakeup.cron
        else f"every {wakeup.interval_minutes}min"
    )
    print(f"scheduled {wakeup.id}: {schedule} -- {wakeup.message}")


def _handle_list() -> None:
    wakeups = list_wakeups()
    if not wakeups:
        print("no pending wakeups")
        return
    for w in wakeups:
        schedule = (
            f"in {w.delay_minutes}min" if w.delay_minutes
            else f"cron '{w.cron}'" if w.cron
            else f"every {w.interval_minutes}min"
        )
        print(f"  {w.id}  {schedule:20s}  {w.message}")


def _handle_cancel(wakeup_id: str) -> None:
    if remove_wakeup(wakeup_id):
        print(f"cancelled {wakeup_id}")
    else:
        print(f"wakeup {wakeup_id} not found")
        sys.exit(1)
