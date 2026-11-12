"""Terminal review. Optional by design: memories you never review are still served, labelled
unconfirmed. Review exists so the owner can approve, restrict, hide or forget on their own schedule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from personakit.model import Decider, Memory, State
from personakit.store import Store

PROPOSED_BY_ASSISTANT = "mcp-proposal"

CHOICES = {"a": State.APPROVED, "r": State.RESTRICTED, "h": State.ARCHIVED}
PROMPT = "  [a]pprove  [r]estrict  [h]ide  [f]orget  [s]kip  [q]uit > "


@dataclass
class ReviewSummary:
    approved: int = 0
    restricted: int = 0
    hidden: int = 0
    forgotten: int = 0
    skipped: int = 0
    remaining: int = 0


def pending(store: Store, limit: int) -> list[Memory]:
    """Unconfirmed memories, oldest first."""
    return store.list(states=[State.UNCONFIRMED])[:limit]


def describe(memory: Memory, position: int, total: int) -> str:
    source = "proposed by an assistant" if any(
        e.session_id == PROPOSED_BY_ASSISTANT for e in memory.evidence
    ) else f"{len(memory.evidence)} quote(s)"
    lines = [f"[{position}/{total}] {memory.text}", f"  {memory.category} · {source}"]
    lines += [f'  "{e.quote}"' for e in memory.evidence[:2]]
    return "\n".join(lines)


def run_review(
    store: Store,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    limit: int = 10,
) -> ReviewSummary:
    summary = ReviewSummary()
    queue = pending(store, limit)
    total_unconfirmed = store.counts()[State.UNCONFIRMED.value]
    if not queue:
        output_fn("Nothing to review.")
        return summary

    for position, memory in enumerate(queue, start=1):
        output_fn(describe(memory, position, len(queue)))
        action = _ask(input_fn, output_fn)
        if action == "q":
            break
        if action == "s":
            summary.skipped += 1
        elif action == "f":
            if input_fn("  Forget this memory and its quotes permanently? [y/N] ").strip().lower() == "y":
                store.forget(memory.id)
                summary.forgotten += 1
            else:
                summary.skipped += 1
        else:
            store.set_state(memory.id, CHOICES[action], Decider.OWNER)
            if action == "a":
                summary.approved += 1
            elif action == "r":
                summary.restricted += 1
            else:
                summary.hidden += 1

    decided = summary.approved + summary.restricted + summary.hidden + summary.forgotten
    summary.remaining = total_unconfirmed - decided
    output_fn(
        f"Done. Approved {summary.approved}, restricted {summary.restricted}, "
        f"hidden {summary.hidden}, forgotten {summary.forgotten}. {summary.remaining} still unconfirmed."
    )
    return summary


def _ask(input_fn: Callable[[str], str], output_fn: Callable[[str], None]) -> str:
    """Read one valid action. End of input counts as quit."""
    while True:
        try:
            answer = input_fn(PROMPT).strip().lower()
        except EOFError:
            return "q"
        if answer in (*CHOICES, "f", "s", "q"):
            return answer
        output_fn("  Please answer a, r, h, f, s or q.")
