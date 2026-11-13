"""The only module that touches SQLite.

Schema, migrations, queries and state changes all live here. Everything else works with
the types in personakit.model.
"""

from __future__ import annotations

import json
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
    # 0.2: when a statement was last seen again (drives decay), and a reversible record of merges.
    # `snapshot` holds the merged-away memory so it can be restored; it is emptied on undo and
    # deleted with its survivor on forget.
    """
    ALTER TABLE memories ADD COLUMN last_seen_at TEXT;
    UPDATE memories SET last_seen_at = created_at;
    CREATE TABLE merges (
        duplicate_id  TEXT PRIMARY KEY,
        survivor_id   TEXT NOT NULL,
        merged_at     TEXT NOT NULL,
        undone_at     TEXT,
        snapshot      TEXT NOT NULL
    );
    """,
]


@dataclass(frozen=True)
class MergeRecord:
    """One memory folded into another. `duplicate_text` is empty once the merge is undone."""

    duplicate_id: str
    survivor_id: str
    merged_at: str
    undone_at: str | None
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

    def add(self, memory: Memory) -> bool:
        """Store a memory. Returns True if it is new.

        If the same memory already exists its evidence is extended and its state is left alone,
        so extracting a fact twice never undoes a decision the owner made. If it was merged into
        another memory, the evidence goes to that memory. Seeing a statement again refreshes
        its last-seen time and brings back a memory that decay had archived.
        """
        with self._conn:
            target = self._merged_into(memory.id) or memory.id
            now = self._now()
            created = (
                target == memory.id
                and self._conn.execute(
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
                ).rowcount
                == 1
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO evidence (memory_id, session_id, turn_index, quote)"
                " VALUES (?, ?, ?, ?)",
                [(target, e.session_id, e.turn_index, e.quote) for e in memory.evidence],
            )
            if not created:
                self._conn.execute("UPDATE memories SET last_seen_at = ? WHERE id = ?", (now, target))
                self._conn.execute(
                    "UPDATE memories SET state = ?, decided_at = NULL, decided_by = NULL"
                    " WHERE id = ? AND state = ? AND decided_by = ?",
                    (State.UNCONFIRMED.value, target, State.ARCHIVED.value, Decider.POLICY.value),
                )
        return created

    def _merged_into(self, memory_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT survivor_id FROM merges WHERE duplicate_id = ? AND undone_at IS NULL", (memory_id,)
        ).fetchone()
        return row["survivor_id"] if row else None

    def merge(self, duplicate_id: str, survivor_id: str) -> None:
        """Fold one unconfirmed memory into another, keeping a record that undo_merge can reverse.

        The duplicate's evidence moves to the survivor and the duplicate disappears from the
        store. Only unconfirmed memories can be merged: an owner's decision is never overridden.
        """
        if duplicate_id == survivor_id:
            raise ValueError("cannot merge a memory into itself")
        duplicate, survivor = self.get(duplicate_id), self.get(survivor_id)
        if duplicate is None or survivor is None:
            raise KeyError(duplicate_id if duplicate is None else survivor_id)
        if duplicate.state != State.UNCONFIRMED or survivor.state != State.UNCONFIRMED:
            raise ValueError("only unconfirmed memories can be merged")
        with self._conn:
            added = [
                [e.session_id, e.turn_index]
                for e in duplicate.evidence
                if self._conn.execute(
                    "INSERT OR IGNORE INTO evidence (memory_id, session_id, turn_index, quote) VALUES (?, ?, ?, ?)",
                    (survivor_id, e.session_id, e.turn_index, e.quote),
                ).rowcount
            ]
            snapshot = {
                "text": duplicate.text,
                "category": duplicate.category,
                "scope": duplicate.scope,
                "created_at": duplicate.created_at,
                "last_seen_at": duplicate.last_seen_at,
                "evidence": [[e.session_id, e.turn_index, e.quote] for e in duplicate.evidence],
                "added": added,
            }
            self._conn.execute("DELETE FROM memories WHERE id = ?", (duplicate_id,))
            self._conn.execute(
                "UPDATE memories SET last_seen_at = MAX(COALESCE(last_seen_at, ''), ?) WHERE id = ?",
                (duplicate.last_seen_at or "", survivor_id),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO merges (duplicate_id, survivor_id, merged_at, undone_at, snapshot)"
                " VALUES (?, ?, ?, NULL, ?)",
                (duplicate_id, survivor_id, self._now(), json.dumps(snapshot)),
            )

    def undo_merge(self, duplicate_id: str) -> None:
        """Bring a merged memory back and take back the evidence it gave. Raises KeyError if
        there is no active merge for that id."""
        row = self._conn.execute(
            "SELECT * FROM merges WHERE duplicate_id = ? AND undone_at IS NULL", (duplicate_id,)
        ).fetchone()
        if row is None:
            raise KeyError(duplicate_id)
        snap = json.loads(row["snapshot"])
        with self._conn:
            self._conn.execute(
                "INSERT INTO memories (id, text, category, scope, state, created_at, last_seen_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    duplicate_id,
                    snap["text"],
                    snap["category"],
                    snap["scope"],
                    State.UNCONFIRMED.value,
                    snap["created_at"],
                    snap["last_seen_at"],
                ),
            )
            self._conn.executemany(
                "INSERT INTO evidence (memory_id, session_id, turn_index, quote) VALUES (?, ?, ?, ?)",
                [(duplicate_id, *e) for e in snap["evidence"]],
            )
            self._conn.executemany(
                "DELETE FROM evidence WHERE memory_id = ? AND session_id = ? AND turn_index = ?",
                [(row["survivor_id"], *key) for key in snap["added"]],
            )
            self._conn.execute(
                "UPDATE merges SET undone_at = ?, snapshot = '{}' WHERE duplicate_id = ?",
                (self._now(), duplicate_id),
            )

    def merges(self, since: str | None = None, active_only: bool = True) -> list[MergeRecord]:
        clauses, params = [], []
        if active_only:
            clauses.append("undone_at IS NULL")
        if since is not None:
            clauses.append("merged_at >= ?")
            params.append(since)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute("SELECT * FROM merges" + where + " ORDER BY merged_at, duplicate_id", params)
        return [
            MergeRecord(
                r["duplicate_id"], r["survivor_id"], r["merged_at"], r["undone_at"],
                json.loads(r["snapshot"]).get("text", ""),
            )
            for r in rows
        ]

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
                "UPDATE memories SET state = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                (state.value, self._now(), by.value, memory_id),
            ).rowcount
        if changed == 0:
            raise KeyError(memory_id)

    def forget(self, memory_id: str) -> bool:
        """Delete a memory and its evidence. Returns False if it did not exist.

        Also deletes what merges kept of it: records that hold this memory as the survivor, and,
        if it had been merged into another memory, the evidence it contributed there.
        """
        with self._conn:
            deleted = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount == 1
            # Records held under this memory, and under anything that was itself merged into it.
            pending = [memory_id]
            while pending:
                rows = self._conn.execute(
                    "SELECT duplicate_id FROM merges WHERE survivor_id = ?", (pending.pop(),)
                ).fetchall()
                self._conn.executemany("DELETE FROM merges WHERE duplicate_id = ?", [(r[0],) for r in rows])
                pending.extend(r[0] for r in rows)
            merged = self._conn.execute("SELECT * FROM merges WHERE duplicate_id = ?", (memory_id,)).fetchone()
            if merged is not None:
                if merged["undone_at"] is None:
                    self._conn.executemany(
                        "DELETE FROM evidence WHERE memory_id = ? AND session_id = ? AND turn_index = ?",
                        [(merged["survivor_id"], *key) for key in json.loads(merged["snapshot"])["added"]],
                    )
                self._conn.execute("DELETE FROM merges WHERE duplicate_id = ?", (memory_id,))
        return deleted or merged is not None

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
            last_seen_at=row["last_seen_at"],
            evidence=evidence,
        )
