"""Plain data types shared by every stage. No I/O lives here."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    """Where a memory stands. Only the owner can approve, restrict or forget."""

    UNCONFIRMED = "unconfirmed"
    APPROVED = "approved"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class Decider(str, Enum):
    """Who moved a memory into its current state."""

    OWNER = "owner"
    POLICY = "policy"


@dataclass(frozen=True)
class Turn:
    """One thing the owner wrote. Assistant replies and tool output never become Turns."""

    source: str
    session_id: str
    index: int
    timestamp: str | None
    text: str


@dataclass
class Session:
    """The owner's turns from one session file, plus a count of what was left out and why."""

    source: str
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    dropped: Counter = field(default_factory=Counter)


@dataclass(frozen=True)
class Evidence:
    """The exact words a memory rests on."""

    session_id: str
    turn_index: int
    quote: str


@dataclass(frozen=True)
class Memory:
    """A short statement about the owner, with the evidence it came from.

    A memory without evidence is rejected at construction, so no later stage
    has to re-check that rule.
    """

    text: str
    category: str
    evidence: tuple[Evidence, ...]
    scope: str = "global"
    state: State = State.UNCONFIRMED
    id: str = ""
    created_at: str | None = None
    decided_at: str | None = None
    decided_by: Decider | None = None
    last_seen_at: str | None = None  # last time the same statement was extracted again

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("memory text must not be empty")
        if not self.evidence:
            raise ValueError("a memory needs at least one piece of evidence")
        if not self.id:
            object.__setattr__(self, "id", memory_id(self.text))

    def as_dict(self) -> dict[str, object]:
        """Machine-readable summary. Quotes are left out: they stay in the owner's store."""
        return {
            "id": self.id,
            "state": self.state.value,
            "category": self.category,
            "scope": self.scope,
            "text": self.text,
            "quotes": len(self.evidence),
            "created_at": self.created_at,
        }


_WHITESPACE = re.compile(r"\s+")


def normalise_text(text: str) -> str:
    """Case- and whitespace-insensitive form used to recognise the same memory twice."""
    return _WHITESPACE.sub(" ", text).strip().lower()


def memory_id(text: str) -> str:
    """Stable id derived from the memory text, so extracting the same fact again merges."""
    digest = hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()
    return "m_" + digest[:12]
