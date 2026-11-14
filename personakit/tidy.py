"""Tidy the store: archive unconfirmed memories that have gone stale.

It is a proposal first. `make_plan` only reads; nothing changes until the owner runs `apply`, and
`undo` reverses any single step. Nothing is ever deleted here, and no memory the owner has
decided on is touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personakit import decay
from personakit.model import Decider, Memory, State
from personakit.store import Store


@dataclass
class Plan:
    stale: list[Memory] = field(default_factory=list)


def make_plan(store: Store, now: str, days: int = decay.DEFAULT_DAYS) -> Plan:
    return Plan(decay.find_stale(store.list(states=[State.UNCONFIRMED]), now, days))


def apply(store: Store, plan: Plan) -> None:
    """Archive what the plan lists."""
    for memory in plan.stale:
        store.set_state(memory.id, State.ARCHIVED, Decider.POLICY)


def undo(store: Store, memory_id: str) -> None:
    """Bring back one memory that tidy archived. Raises KeyError for anything else, including
    memories the owner archived themselves."""
    store.restore(memory_id)
