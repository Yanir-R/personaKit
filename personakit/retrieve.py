"""Which memories an assistant may see, and which ones answer a question.

This is the one read policy. The MCP server uses it, and so does anything else that shows memories
to an assistant. Approved and unconfirmed memories are served (unconfirmed ones are labelled as
such); restricted and archived memories are never served.

Ranking is word overlap. It is a deliberately simple baseline, not a finished retriever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from personakit.model import Memory, State

SERVED = (State.APPROVED, State.UNCONFIRMED)

# When fewer than this many memories match the question, approved ones fill the rest, so an
# assistant always gets the owner's confirmed standing preferences.
STANDING_CONTEXT = 3

_WORD = re.compile(r"[a-z0-9']{3,}")
_STOP = frozenset(
    "the and for you your with that this have from what how should about are was were not but "
    "can will would could into than then them they their there when where which who why".split()
)


@dataclass(frozen=True)
class Result:
    memories: list[Memory]
    withheld: int  # matching memories the owner restricted, counted but never shown


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def search(memories: Iterable[Memory], question: str, limit: int = 7) -> Result:
    asked = words(question)
    scored, standing, withheld = [], [], 0
    for memory in memories:
        overlap = len(asked & words(memory.text + " " + memory.category))
        if memory.state == State.RESTRICTED:
            withheld += overlap > 0
        elif memory.state in SERVED:
            if overlap:
                scored.append((overlap, memory))
            elif memory.state == State.APPROVED:
                standing.append(memory)

    # Best overlap first; approved before unconfirmed; then oldest first for a stable order.
    scored.sort(key=lambda s: (-s[0], s[1].state != State.APPROVED, s[1].created_at or "", s[1].id))
    chosen = [memory for _, memory in scored][:limit]
    fill = min(limit, STANDING_CONTEXT) - len(chosen)
    if fill > 0:
        chosen.extend(sorted(standing, key=lambda m: (m.created_at or "", m.id))[:fill])
    return Result(chosen, withheld)
