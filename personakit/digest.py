"""A short summary of the last few days in your own store.

Unlike `stats`, a digest shows memory ids and text (never evidence quotes) so you can see what
changed. It is printed to your terminal and goes nowhere else. Run it weekly from cron or a
scheduler if you want a routine; PersonaKit does not schedule anything itself.
"""

from __future__ import annotations

from personakit import decay
from personakit.model import Decider, Memory, State
from personakit.store import Store

LISTED = 10  # most memories shown per section


def collect(store: Store, now: str, days: int = 7) -> dict:
    since = decay.days_ago(now, days)
    everything = store.list()
    new = [m for m in everything if (m.created_at or "") >= since]
    archived = [
        m for m in everything if m.state == State.ARCHIVED and m.decided_by == Decider.POLICY and (m.decided_at or "") >= since
    ]
    return {
        "days": days,
        "new": len(new),
        "new_items": _items(new),
        "archived_by_decay": len(archived),
        "archived_items": _items(archived),
        "awaiting_review": store.counts()[State.UNCONFIRMED.value],
        **store.read_stats(since),
    }


def _items(memories: list[Memory]) -> list[dict[str, str]]:
    return [{"id": m.id, "text": m.text} for m in memories[:LISTED]]


def format_digest(data: dict) -> str:
    lines = [f"PersonaKit digest, last {data['days']} days"]
    for label, count, items in (
        ("New memories", data["new"], data["new_items"]),
        ("Archived as stale (undo with `personakit undo <id>`)", data["archived_by_decay"], data["archived_items"]),
    ):
        lines.append(f"{label}: {count}")
        lines += [f"  {item['id']}  {item['text']}" for item in items]
        if count > len(items):
            lines.append(f"  ... and {count - len(items)} more")
    lines.append(f"Awaiting your review: {data['awaiting_review']}")
    lines.append(f"Assistant reads: {data['reads']} ({data['reads_with_results']} returned something)")
    return "\n".join(lines)
