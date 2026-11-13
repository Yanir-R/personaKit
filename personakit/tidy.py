"""Tidy the store: fold same-session twins together and archive stale memories.

Both steps are proposals first. `plan` only reads; nothing changes until the owner runs `apply`,
and everything `apply` does can be reversed with `undo`. Nothing is ever deleted here, and no
memory the owner has decided on is touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personakit import decay, twins
from personakit.model import Decider, State
from personakit.store import Store


@dataclass
class Plan:
    groups: list[twins.TwinGroup] = field(default_factory=list)
    stale: list = field(default_factory=list)

    @property
    def merges(self) -> int:
        return sum(len(g.duplicates) for g in self.groups)


@dataclass
class Report:
    merged: int = 0
    archived: int = 0


def make_plan(
    store: Store,
    now: str,
    days: int = decay.DEFAULT_DAYS,
    threshold: float = twins.DEFAULT_THRESHOLD,
    merge: bool = True,
    archive: bool = True,
) -> Plan:
    plan = Plan()
    if merge:
        undone = frozenset(
            frozenset((r.duplicate_id, r.survivor_id)) for r in store.merges(active_only=False) if r.undone_at
        )
        plan.groups = twins.find_twins(store.list(states=[State.UNCONFIRMED]), threshold, undone)
    if archive:
        folded = {d.id for g in plan.groups for d in g.duplicates}  # about to disappear, so not archived too
        plan.stale = [m for m in decay.find_stale(store.list(states=[State.UNCONFIRMED]), now, days) if m.id not in folded]
    return plan


def apply(store: Store, plan: Plan) -> Report:
    report = Report()
    for group in plan.groups:
        for duplicate in group.duplicates:
            store.merge(duplicate.id, group.survivor.id)
            report.merged += 1
    for memory in plan.stale:
        store.set_state(memory.id, State.ARCHIVED, Decider.POLICY)
        report.archived += 1
    return report


def undo(store: Store, memory_id: str) -> str:
    """Reverse one merge or one decay archive. Returns "unmerged" or "restored".

    Raises KeyError for anything else, including memories the owner archived themselves.
    """
    try:
        store.undo_merge(memory_id)
        return "unmerged"
    except KeyError:
        store.restore(memory_id)
        return "restored"
