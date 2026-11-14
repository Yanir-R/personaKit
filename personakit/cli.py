"""Command line entry point. Parses arguments and wires modules together; holds no logic of its own."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from personakit import decay, digest, llm, mcp_server, review, stats, sweep, tidy
from personakit.ingest import ADAPTERS
from personakit.model import State
from personakit.store import Store

MAX_DAYS = 36500
CLIENTS = {"claude": llm.ClaudeCli, "codex": llm.CodexCli}


def default_db() -> Path:
    return Path(os.environ.get("PERSONAKIT_DB") or Path.home() / ".personakit" / "store.db")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personakit", description="Memory you can read, correct and take with you.")
    parser.add_argument("--db", type=Path, default=None, help="store file (default: $PERSONAKIT_DB or ~/.personakit/store.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("sweep", help="read new sessions and extract memories")
    run.add_argument("--source", choices=[*ADAPTERS, "all"], default="all")
    run.add_argument("--cli", choices=list(CLIENTS), default="claude", help="which signed-in CLI runs extraction")
    run.add_argument("--model", required=True, help="model name; never defaulted")
    run.add_argument("--max-calls", type=int, default=50, help="most model calls this run may make")
    run.add_argument("--max-sessions", type=int, default=None)
    run.add_argument("--json", action="store_true", help="print one JSON object per source")
    run.add_argument("--root", type=Path, default=None, help="session directory (only valid with a single --source)")

    rev = sub.add_parser("review", help="approve, restrict, hide or forget memories")
    rev.add_argument("--limit", type=int, default=10)

    lst = sub.add_parser("list", help="list memories")
    lst.add_argument("--state", choices=[s.value for s in State], default=None)
    lst.add_argument("--json", action="store_true", help="print a JSON array (no quotes)")

    stats_cmd = sub.add_parser("stats", help="counts only, never memory text")
    stats_cmd.add_argument("--json", action="store_true", help="print a JSON object")

    tidy_cmd = sub.add_parser("tidy", help="archive stale unconfirmed memories (shows a plan; --apply to act)")
    tidy_cmd.add_argument("--apply", action="store_true", help="carry out the plan instead of only showing it")
    tidy_cmd.add_argument("--days", type=int, default=decay.DEFAULT_DAYS, help="days unseen before unconfirmed is stale")
    tidy_cmd.add_argument("--json", action="store_true", help="print a JSON object (ids only)")

    undo_cmd = sub.add_parser("undo", help="bring back one memory that tidy archived")
    undo_cmd.add_argument("memory_id")

    digest_cmd = sub.add_parser("digest", help="what changed in the last days (prints memory text, locally)")
    digest_cmd.add_argument("--days", type=int, default=7)
    digest_cmd.add_argument("--json", action="store_true", help="print a JSON object")

    forget = sub.add_parser("forget", help="permanently delete a memory and its quotes")
    forget.add_argument("memory_id")

    sub.add_parser("serve", help="run the MCP server over stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = args.db or default_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    with Store(db) as store:
        return _dispatch(args, store)


def _dispatch(args: argparse.Namespace, store: Store) -> int:
    if args.command == "sweep":
        return _sweep(args, store)
    if args.command == "review":
        review.run_review(store, limit=args.limit)
    elif args.command == "list":
        states = [State(args.state)] if args.state else None
        memories = store.list(states=states)
        if args.json:
            _print_json([m.as_dict() for m in memories])
        else:
            for memory in memories:
                print(f"{memory.id}  {memory.state.value:<11} {memory.text}")
    elif args.command == "stats":
        collected = stats.collect(store)
        if args.json:
            _print_json(collected)
        else:
            print(stats.format_stats(collected))
    elif args.command == "tidy":
        return _tidy(args, store)
    elif args.command == "undo":
        try:
            tidy.undo(store, args.memory_id)
        except KeyError:
            print(f"Nothing to undo for {args.memory_id}: tidy did not archive it", file=sys.stderr)
            return 1
        print("Restored.")
    elif args.command == "digest":
        if not 1 <= args.days <= MAX_DAYS:
            print(f"--days must be between 1 and {MAX_DAYS}", file=sys.stderr)
            return 2
        collected = digest.collect(store, store.now(), args.days)
        if args.json:
            _print_json(collected)
        else:
            print(digest.format_digest(collected))
    elif args.command == "forget":
        if not store.forget(args.memory_id):
            print(f"No memory with id {args.memory_id}", file=sys.stderr)
            return 1
        print("Forgotten.")
    elif args.command == "serve":
        mcp_server.serve(store)
    return 0


def _print_json(data: object) -> None:
    """One stable, sorted JSON document per call, so output is byte-for-byte repeatable."""
    print(json.dumps(data, sort_keys=True, ensure_ascii=False))


def _tidy(args: argparse.Namespace, store: Store) -> int:
    if not 1 <= args.days <= MAX_DAYS:
        print(f"--days must be between 1 and {MAX_DAYS}", file=sys.stderr)
        return 2
    plan = tidy.make_plan(store, store.now(), args.days)
    if args.apply:
        tidy.apply(store, plan)
    if args.json:
        _print_json({"applied": args.apply, "archive": [m.id for m in plan.stale]})
        return 0
    for memory in plan.stale:
        print(f"archive {memory.id}  {memory.text}")
    if not plan.stale:
        print("Nothing to tidy.")
    elif args.apply:
        print(f"Archived {len(plan.stale)}. Reverse any with: personakit undo <id>")
    else:
        print(f"{len(plan.stale)} to archive. Nothing changed; add --apply to carry it out.")
    return 0


def _sweep(args: argparse.Namespace, store: Store) -> int:
    sources = list(ADAPTERS) if args.source == "all" else [args.source]
    if args.root and len(sources) != 1:
        print("--root needs a single --source", file=sys.stderr)
        return 2
    client = llm.BudgetedClient(CLIENTS[args.cli](args.model), llm.Budget(args.max_calls))
    exit_code = 0
    for source in sources:
        report = sweep.sweep(store, ADAPTERS[source], client, root=args.root, max_sessions=args.max_sessions)
        if args.json:
            _print_json({"source": source, **report.as_dict()})
        else:
            print(
                f"{source}: {report.sessions_found} sessions, {report.sessions_extracted} extracted, "
                f"{report.sessions_unchanged} unchanged, {report.memories_new} new memories, "
                f"{report.memories_merged} merged"
                + (f", stopped: {report.stopped}" if report.stopped else "")
            )
        if report.stopped and report.stopped.startswith("model_error"):
            exit_code = 1
            break
        if report.stopped == "budget":
            break
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
