"""Which memories an assistant may see, and which ones answer a question.

This is the one read policy. The MCP server uses it, and so does anything else that shows memories
to an assistant. Approved and unconfirmed memories are served (unconfirmed ones are labelled as
such); restricted and archived memories are never served.

Ranking is word overlap. It is a deliberately simple baseline, not a finished retriever.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from personakit.model import Memory, State

SERVED = (State.APPROVED, State.UNCONFIRMED)

# When fewer than this many memories match the question, approved ones fill the rest, so an
# assistant always gets the owner's confirmed standing preferences.
STANDING_CONTEXT = 3

# Evidence quotes are shortened and email-masked before an assistant sees them.
SERVED_QUOTE_CHARS = 240
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

_WORD = re.compile(r"[a-z0-9']{3,}")
STOP_WORDS = frozenset(
    "the and for you your with that this have from what how should about are was were not but "
    "can will would could into than then them they their there when where which who why".split()
)


@dataclass(frozen=True)
class Result:
    memories: list[Memory]
    withheld: int  # matching memories the owner restricted, counted but never shown


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP_WORDS}


def overlap(question: str, memories: Sequence[Memory]) -> list[float]:
    """The built-in relevance: how many words of the question each memory shares."""
    asked = words(question)
    return [float(len(asked & words(m.text + " " + m.category))) for m in memories]


Relevance = Callable[[str, Sequence[Memory]], Sequence[float]]


def search(memories: Iterable[Memory], question: str, limit: int = 7, relevance: Relevance = overlap) -> Result:
    """Apply the read policy. `relevance` only orders memories (above 0 means relevant); what may
    be served is decided here and cannot be widened by it."""
    memories = list(memories)
    scored, standing, withheld = [], [], 0
    for memory, score in zip(memories, relevance(question, memories), strict=True):
        if memory.state == State.RESTRICTED:
            withheld += score > 0
        elif memory.state in SERVED:
            if score > 0:
                scored.append((score, memory))
            elif memory.state == State.APPROVED:
                standing.append(memory)

    # Most relevant first; approved before unconfirmed; then oldest first for a stable order.
    scored.sort(key=lambda s: (-s[0], s[1].state != State.APPROVED, s[1].created_at or "", s[1].id))
    chosen = [memory for _, memory in scored][:limit]
    fill = min(limit, STANDING_CONTEXT) - len(chosen)
    if fill > 0:
        chosen.extend(sorted(standing, key=lambda m: (m.created_at or "", m.id))[:fill])
    return Result(chosen, withheld)


def served_quote(quote: str) -> str:
    """The form of a quote an assistant receives: emails masked, cut at a word boundary.

    The store keeps the quote verbatim for the owner's own review; assistants get a shorter,
    masked copy.
    """
    text = _EMAIL.sub("[email]", " ".join(quote.split()))
    if len(text) <= SERVED_QUOTE_CHARS:
        return text
    cut = text[:SERVED_QUOTE_CHARS]
    ends = [cut.rfind(mark) for mark in (". ", "? ", "! ")]
    if max(ends) >= SERVED_QUOTE_CHARS // 2:
        return cut[: max(ends) + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"
