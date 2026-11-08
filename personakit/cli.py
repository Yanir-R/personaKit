"""Command line entry point. Parses arguments and wires modules together; holds no logic of its own."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from personakit import llm, mcp_server, review, stats, sweep
from personakit.ingest import ADAPTERS
from personakit.model import State
from personakit.store import Store

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
    run.add_argument("--root", type=Path, default=None, help="session directory (only valid with a single --source)")

    rev = sub.add_parser("review", help="approve, restrict, hide or forget memories")
    rev.add_argument("--limit", type=int, default=10)

    lst = sub.add_parser("list", help="list memories")
    lst.add_argument("--state", choices=[s.value for s in State], default=None)

    sub.add_parser("stats", help="counts only, never memory text")

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
        for memory in store.list(states=states):
            print(f"{memory.id}  {memory.state.value:<11} {memory.text}")
    elif args.command == "stats":
        print(stats.format_stats(stats.collect(store)))
    elif args.command == "forget":
        if not store.forget(args.memory_id):
            print(f"No memory with id {args.memory_id}", file=sys.stderr)
            return 1
        print("Forgotten.")
    elif args.command == "serve":
        mcp_server.serve(store)
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
