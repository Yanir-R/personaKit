"""The only module that touches SQLite.

Schema, migrations, queries and state changes all live here. Everything else works with
the types in personakit.model.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from personakit.model import Decider, Evidence, Memory, State

# Each entry upgrades the database by one version. Never edit an entry that has shipped;
# append a new one.
MIGRATIONS = [
    """
    CREATE TABLE memories (
        id          TEXT PRIMARY KEY,
        text        TEXT NOT NULL,
        category    TEXT NOT NULL,
        scope       TEXT NOT NULL,
        state       TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        decided_at  TEXT,
        decided_by  TEXT
    );
    CREATE TABLE evidence (
        memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
        session_id  TEXT NOT NULL,
        turn_index  INTEGER NOT NULL,
        quote       TEXT NOT NULL,
        PRIMARY KEY (memory_id, session_id, turn_index)
    );
    CREATE TABLE sessions_seen (
        source       TEXT NOT NULL,
        session_id   TEXT NOT NULL,
        fingerprint  TEXT NOT NULL,
        seen_at      TEXT NOT NULL,
        PRIMARY KEY (source, session_id)
    );
    """,
    """
    CREATE TABLE reads (
        at        TEXT NOT NULL,
        returned  INTEGER NOT NULL,
        withheld  INTEGER NOT NULL
    );
    """,
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: str | Path, now: Callable[[], str] = _utc_now):
        self._now = now
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise RuntimeError(
                f"database is version {version}, newer than this PersonaKit ({len(MIGRATIONS)})"
            )
        for number in range(version, len(MIGRATIONS)):
            with self._conn:
                self._conn.executescript("BEGIN;" + MIGRATIONS[number])
                self._conn.execute(f"PRAGMA user_version = {number + 1}")

    # -- writing --------------------------------------------------------------------

    def add(self, memory: Memory) -> bool:
        """Store a memory. Returns True if it is new.

        If the same memory already exists its evidence is extended and its state is left alone,
        so extracting a fact twice never undoes a decision the owner made.
        """
        with self._conn:
            created = self._conn.execute(
                "INSERT OR IGNORE INTO memories"
                " (id, text, category, scope, state, created_at, decided_at, decided_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory.id,
                    memory.text,
                    memory.category,
                    memory.scope,
                    memory.state.value,
                    memory.created_at or self._now(),
                    memory.decided_at,
                    memory.decided_by.value if memory.decided_by else None,
                ),
            ).rowcount == 1
            self._conn.executemany(
                "INSERT OR IGNORE INTO evidence (memory_id, session_id, turn_index, quote)"
                " VALUES (?, ?, ?, ?)",
                [(memory.id, e.session_id, e.turn_index, e.quote) for e in memory.evidence],
            )
        return created

    def set_state(self, memory_id: str, state: State, by: Decider) -> None:
        """Move a memory to a new state and record who did it. Raises KeyError if unknown."""
        with self._conn:
            changed = self._conn.execute(
                "UPDATE memories SET state = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                (state.value, self._now(), by.value, memory_id),
            ).rowcount
        if changed == 0:
            raise KeyError(memory_id)

    def forget(self, memory_id: str) -> bool:
        """Delete a memory and its evidence. Returns False if it did not exist."""
        with self._conn:
            return self._conn.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            ).rowcount == 1

    def mark_session_seen(self, source: str, session_id: str, fingerprint: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions_seen (source, session_id, fingerprint, seen_at)"
                " VALUES (?, ?, ?, ?)",
                (source, session_id, fingerprint, self._now()),
            )

    def log_read(self, returned: int, withheld: int) -> None:
        """Record that an assistant asked for memories. Counts only, never the question."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO reads (at, returned, withheld) VALUES (?, ?, ?)",
                (self._now(), returned, withheld),
            )

    # -- reading --------------------------------------------------------------------

    def read_stats(self) -> dict[str, int]:
        row = self._conn.execute(
            "SELECT COUNT(*) AS reads, COALESCE(SUM(returned > 0), 0) AS with_results FROM reads"
        ).fetchone()
        return {"reads": row["reads"], "reads_with_results": row["with_results"]}

    def session_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM sessions_seen").fetchone()[0]

    def session_is_current(self, source: str, session_id: str, fingerprint: str) -> bool:
        row = self._conn.execute(
            "SELECT fingerprint FROM sessions_seen WHERE source = ? AND session_id = ?",
            (source, session_id),
        ).fetchone()
        return row is not None and row["fingerprint"] == fingerprint

    def get(self, memory_id: str) -> Memory | None:
        row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._load(row) if row else None

    def list(
        self, states: Iterable[State] | None = None, scope: str | None = None
    ) -> list[Memory]:
        clauses, params = [], []
        if states is not None:
            values = [s.value for s in states]
            clauses.append(f"state IN ({','.join('?' * len(values))})")
            params.extend(values)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            "SELECT * FROM memories" + where + " ORDER BY created_at, rowid", params
        ).fetchall()
        evidence: dict[str, list[Evidence]] = {}
        for r in self._conn.execute(
            "SELECT * FROM evidence WHERE memory_id IN (SELECT id FROM memories" + where + ")"
            " ORDER BY memory_id, session_id, turn_index",
            params,
        ):
            evidence.setdefault(r["memory_id"], []).append(
                Evidence(r["session_id"], r["turn_index"], r["quote"])
            )
        return [self._build(row, tuple(evidence.get(row["id"], ()))) for row in rows]

    def counts(self) -> dict[str, int]:
        """Number of memories in each state. Counts only, never content."""
        result = {state.value: 0 for state in State}
        for row in self._conn.execute("SELECT state, COUNT(*) AS n FROM memories GROUP BY state"):
            result[row["state"]] = row["n"]
        return result

    def _load(self, row: sqlite3.Row) -> Memory:
        evidence = tuple(
            Evidence(r["session_id"], r["turn_index"], r["quote"])
            for r in self._conn.execute(
                "SELECT * FROM evidence WHERE memory_id = ? ORDER BY session_id, turn_index",
                (row["id"],),
            )
        )
        return self._build(row, evidence)

    @staticmethod
    def _build(row: sqlite3.Row, evidence: tuple[Evidence, ...]) -> Memory:
        return Memory(
            id=row["id"],
            text=row["text"],
            category=row["category"],
            scope=row["scope"],
            state=State(row["state"]),
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            decided_by=Decider(row["decided_by"]) if row["decided_by"] else None,
            evidence=evidence,
        )
