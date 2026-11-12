"""Read new sessions, extract memories, store them.

A sweep never stops because unreviewed memories are piling up: review is optional, so a growing
backlog is not a reason to stop collecting. It stops only when the call budget is used up or the
model reports an error (for example, not signed in), and it never marks a session as done unless
that session was actually extracted.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType

from personakit.extract import extract_session
from personakit.llm import BudgetExceeded, ModelClient, ModelError
from personakit.store import Store


@dataclass
class SweepReport:
    sessions_found: int = 0
    sessions_unchanged: int = 0
    sessions_extracted: int = 0
    memories_new: int = 0
    memories_merged: int = 0
    rejected: Counter = field(default_factory=Counter)
    stopped: str | None = None

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["rejected"] = dict(sorted(self.rejected.items()))
        return data


def fingerprint(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:16]


def sweep(
    store: Store,
    adapter: ModuleType,
    client: ModelClient,
    root: Path | None = None,
    max_sessions: int | None = None,
) -> SweepReport:
    report = SweepReport()
    paths = adapter.discover(root)
    report.sessions_found = len(paths)

    for path in paths:
        key, current = path.stem, fingerprint(path)  # keyed by file, not by the id inside it
        if store.session_is_current(adapter.SOURCE, key, current):
            report.sessions_unchanged += 1
            continue
        if max_sessions is not None and report.sessions_extracted >= max_sessions:
            report.stopped = "max_sessions"
            break

        session = adapter.read_session(path)
        try:
            result = extract_session(session, client)
        except BudgetExceeded:
            report.stopped = "budget"
            break
        except ModelError as exc:
            report.stopped = f"model_error: {exc}"
            break

        for memory in result.memories:
            if store.add(memory):
                report.memories_new += 1
            else:
                report.memories_merged += 1
        report.rejected.update(result.rejected)
        store.mark_session_seen(adapter.SOURCE, key, current)
        report.sessions_extracted += 1
    return report

