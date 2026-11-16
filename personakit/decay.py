"""Which unconfirmed memories have gone stale.

A memory is stale when it is still unconfirmed and has not been extracted again for a long time.
Approved and restricted memories never decay: those are the owner's decisions. Staleness only
ever leads to archiving (reversible), never to deletion.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from personakit.model import Memory, State

DEFAULT_DAYS = 90
_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def days_ago(now: str, days: int) -> str:
    """The timestamp `days` before `now`, in the store's format, so strings compare in time order."""
    moment = datetime.strptime(now, _FORMAT).replace(tzinfo=timezone.utc)
    return (moment - timedelta(days=days)).strftime(_FORMAT)


def find_stale(memories: Iterable[Memory], now: str, days: int = DEFAULT_DAYS) -> list[Memory]:
    if days < 1:
        raise ValueError("days must be at least 1")
    cutoff = days_ago(now, days)
    return [
        m
        for m in memories
        if m.state == State.UNCONFIRMED and (m.last_seen_at or m.created_at or now) < cutoff
    ]
