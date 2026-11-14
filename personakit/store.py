"""The only module that touches SQLite.

Schema, migrations, queries and state changes all live here. Everything else works with
the types in personakit.model.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
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
    # 0.2: when a statement was last seen again (drives decay), and reversible merges. A merged
    # memory keeps its own row and evidence and points at the memory it was folded into, so
    # undoing is exact and forgetting either one leaves nothing behind.
    """
    ALTER TABLE memories ADD COLUMN last_seen_at TEXT;
    ALTER TABLE memories ADD COLUMN merged_into TEXT REFERENCES memories(id) ON DELETE CASCADE;
    ALTER TABLE memories ADD COLUMN merged_at TEXT;
    UPDATE memories SET last_seen_at = created_at;
    CREATE TABLE merge_vetoes (
        first_id   TEXT NOT NULL,
        second_id  TEXT NOT NULL,
        PRIMARY KEY (first_id, second_id)
    );
    """,
]

# A memory together with everything folded into it, directly or through another folded memory.
_GROUP = (
    "WITH RECURSIVE grp(id) AS (SELECT ? UNION SELECT m.id FROM memories m JOIN grp ON m.merged_into = grp.id) "
)


@dataclass(frozen=True)
class MergeRecord:
    """One memory folded into another."""

    duplicate_id: str
    survivor_id: str
    merged_at: str
    duplicate_text: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: str | Path, now: Callable[[], str] = _utc_now):
        self._now = now
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def now(self) -> str:
        """The store's clock, in the format it records."""
        return self._now()

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

    def add(self, memory: Memory, observed: bool = True) -> bool:
        """Store a memory. Returns True if it is new.

        If the same memory already exists its evidence is extended and its state is left alone,
        so extracting a fact twice never undoes a decision the owner made. `observed` says the
        owner was seen stating it again (an extraction): that refreshes its last-seen time and
        brings back a memory that decay had archived. An assistant's proposal is not an
        observation and does neither.
        """
        with self._conn:
            now = self._now()
            created = self._conn.execute(
                "INSERT OR IGNORE INTO memories"
                " (id, text, category, scope, state, created_at, last_seen_at, decided_at, decided_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory.id,
                    memory.text,
                    memory.category,
                    memory.scope,
                    memory.state.value,
                    memory.created_at or now,
                    memory.last_seen_at or memory.created_at or now,
                    memory.decided_at,
                    memory.decided_by.value if memory.decided_by else None,
                ),
            ).rowcount == 1
            self._conn.executemany(
                "INSERT OR IGNORE INTO evidence (memory_id, session_id, turn_index, quote)"
                " VALUES (?, ?, ?, ?)",
                [(memory.id, e.session_id, e.turn_index, e.quote) for e in memory.evidence],
            )
            if observed and not created:
                self._conn.execute("UPDATE memories SET last_seen_at = ? WHERE id = ?", (now, memory.id))
                self._conn.execute(
                    "UPDATE memories SET state = ?, decided_at = NULL, decided_by = NULL"
                    " WHERE id = ? AND state = ? AND decided_by = ?",
                    (State.UNCONFIRMED.value, memory.id, State.ARCHIVED.value, Decider.POLICY.value),
                )
        return created

    def merge(self, duplicate_id: str, survivor_id: str) -> None:
        """Fold one unconfirmed memory into another. `undo_merge` reverses it exactly.

        The duplicate keeps its row and evidence but is no longer listed or served on its own;
        the survivor shows the evidence of both. Only unconfirmed memories can be merged, so an
        owner's decision is never overridden.
        """
        if duplicate_id == survivor_id:
            raise ValueError("cannot merge a memory into itself")
        duplicate, survivor = self.get(duplicate_id), self.get(survivor_id)
        if duplicate is None or survivor is None:
            raise KeyError(duplicate_id if duplicate is None else survivor_id)
        if duplicate.state != State.UNCONFIRMED or survivor.state != State.UNCONFIRMED:
            raise ValueError("only unconfirmed memories can be merged")
        with self._conn:
            self._conn.execute(
                "UPDATE memories SET merged_into = ?, merged_at = ? WHERE id = ?",
                (survivor_id, self._now(), duplicate_id),
            )

    def undo_merge(self, duplicate_id: str) -> None:
        """Make a merged memory stand on its own again, and never propose that pair again.
        Raises KeyError if the memory is not merged."""
        row = self._conn.execute(
            "SELECT merged_into FROM memories WHERE id = ? AND merged_into IS NOT NULL", (duplicate_id,)
        ).fetchone()
        if row is None:
            raise KeyError(duplicate_id)
        with self._conn:
            self._conn.execute("UPDATE memories SET merged_into = NULL, merged_at = NULL WHERE id = ?", (duplicate_id,))
            self._conn.execute(
                "INSERT OR IGNORE INTO merge_vetoes (first_id, second_id) VALUES (?, ?)",
                tuple(sorted((duplicate_id, row["merged_into"]))),
            )

    def merges(self, since: str | None = None) -> list[MergeRecord]:
        """Memories currently folded into another, oldest merge first."""
        rows = self._conn.execute(
            "SELECT id, merged_into, merged_at, text FROM memories"
            " WHERE merged_into IS NOT NULL AND merged_at >= ? ORDER BY merged_at, id",
            (since or "",),
        )
        return [MergeRecord(r["id"], r["merged_into"], r["merged_at"], r["text"]) for r in rows]

    def merge_vetoes(self) -> frozenset[frozenset[str]]:
        """Pairs the owner un-merged. They are never proposed as twins again."""
        return frozenset(
            frozenset((r["first_id"], r["second_id"])) for r in self._conn.execute("SELECT * FROM merge_vetoes")
        )

    def restore(self, memory_id: str) -> None:
        """Bring back a memory that decay archived. Raises KeyError unless policy archived it."""
        with self._conn:
            changed = self._conn.execute(
                "UPDATE memories SET state = ?, decided_at = NULL, decided_by = NULL, last_seen_at = ?"
                " WHERE id = ? AND state = ? AND decided_by = ?",
                (State.UNCONFIRMED.value, self._now(), memory_id, State.ARCHIVED.value, Decider.POLICY.value),
            ).rowcount
        if changed == 0:
            raise KeyError(memory_id)

    def set_state(self, memory_id: str, state: State, by: Decider) -> None:
        """Move a memory to a new state and record who did it. Raises KeyError if unknown."""
        with self._conn:
            changed = self._conn.execute(
                "UPDATE memories SET state = ?, decided_at = ?, decided_by = ?"
                " WHERE id = ? AND merged_into IS NULL",
                (state.value, self._now(), by.value, memory_id),
            ).rowcount
        if changed == 0:
            raise KeyError(memory_id)

    def forget(self, memory_id: str) -> bool:
        """Delete a memory and its evidence. Returns False if it did not exist.

        Memories folded into it are the same statement and go with it. A memory that is itself
        folded into another can be forgotten by its id; the other memory stays.
        """
        with self._conn:
            deleted = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount == 1
            self._conn.execute(
                "DELETE FROM merge_vetoes WHERE first_id NOT IN (SELECT id FROM memories)"
                " OR second_id NOT IN (SELECT id FROM memories)"
            )
        return deleted

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

    def read_stats(self, since: str | None = None) -> dict[str, int]:
        row = self._conn.execute(
            "SELECT COUNT(*) AS reads, COALESCE(SUM(returned > 0), 0) AS with_results FROM reads WHERE at >= ?",
            (since or "",),
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
        """One memory with the evidence of everything folded into it. None for an unknown id or
        a memory that is itself folded into another."""
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ? AND merged_into IS NULL", (memory_id,)
        ).fetchone()
        if row is None:
            return None
        evidence = self._conn.execute(
            _GROUP + "SELECT e.* FROM evidence e JOIN grp ON e.memory_id = grp.id", (memory_id,)
        ).fetchall()
        seen = self._conn.execute(
            _GROUP + "SELECT MAX(m.last_seen_at) FROM memories m JOIN grp ON m.id = grp.id", (memory_id,)
        ).fetchone()[0]
        return self._build(row, _own_first(evidence, memory_id), seen)

    def list(
        self, states: Iterable[State] | None = None, scope: str | None = None
    ) -> list[Memory]:
        clauses, params = ["merged_into IS NULL"], []
        if states is not None:
            values = [s.value for s in states]
            clauses.append(f"state IN ({','.join('?' * len(values))})")
            params.extend(values)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE " + " AND ".join(clauses) + " ORDER BY created_at, rowid", params
        ).fetchall()

        # Evidence and last-seen time of folded memories count towards the memory they end up in.
        folded = dict(self._conn.execute("SELECT id, merged_into FROM memories WHERE merged_into IS NOT NULL"))
        seen_by = dict(self._conn.execute("SELECT id, last_seen_at FROM memories WHERE merged_into IS NOT NULL"))

        def root(memory_id: str) -> str:
            while memory_id in folded:
                memory_id = folded[memory_id]
            return memory_id

        evidence: dict[str, list[sqlite3.Row]] = {}
        for r in self._conn.execute("SELECT * FROM evidence"):
            evidence.setdefault(root(r["memory_id"]), []).append(r)
        last_seen: dict[str, str] = {}
        for memory_id, seen in seen_by.items():
            last_seen[root(memory_id)] = max(last_seen.get(root(memory_id), ""), seen or "")
        return [
            self._build(
                row,
                _own_first(evidence.get(row["id"], ()), row["id"]),
                max(row["last_seen_at"] or "", last_seen.get(row["id"], "")) or None,
            )
            for row in rows
        ]

    def counts(self) -> dict[str, int]:
        """Number of memories in each state. Counts only, never content."""
        result = {state.value: 0 for state in State}
        for row in self._conn.execute(
            "SELECT state, COUNT(*) AS n FROM memories WHERE merged_into IS NULL GROUP BY state"
        ):
            result[row["state"]] = row["n"]
        return result

    @staticmethod
    def _build(row: sqlite3.Row, evidence: tuple[Evidence, ...], last_seen_at: str | None) -> Memory:
        return Memory(
            id=row["id"],
            text=row["text"],
            category=row["category"],
            scope=row["scope"],
            state=State(row["state"]),
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            decided_by=Decider(row["decided_by"]) if row["decided_by"] else None,
            last_seen_at=last_seen_at,
            evidence=evidence,
        )


def _own_first(rows: Iterable[sqlite3.Row], memory_id: str) -> tuple[Evidence, ...]:
    """Evidence in session and turn order, one per turn, preferring the memory's own quote."""
    unique: dict[tuple[str, int], Evidence] = {}
    for r in sorted(rows, key=lambda r: (r["session_id"], r["turn_index"], r["memory_id"] != memory_id)):
        unique.setdefault((r["session_id"], r["turn_index"]), Evidence(r["session_id"], r["turn_index"], r["quote"]))
    return tuple(unique.values())
