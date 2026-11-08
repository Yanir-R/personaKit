"""Counts about your own store. Never memory text, never questions.

Printing these is always local. Sharing the output is up to the owner.
"""

from __future__ import annotations

from personakit.store import Store


def collect(store: Store) -> dict[str, int]:
    stats = {f"memories_{state}": n for state, n in store.counts().items()}
    stats["memories_total"] = sum(store.counts().values())
    stats["sessions_extracted"] = store.session_count()
    stats.update(store.read_stats())
    return stats


def format_stats(stats: dict[str, int]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in stats.items())
