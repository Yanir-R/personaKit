"""Which memories an assistant may see, and which ones answer a question.

This is the one read policy. The MCP server uses it, and so does anything else that shows memories
to an assistant. Approved and unconfirmed memories are served (unconfirmed ones are labelled as
such); restricted and archived memories are never served.

Ranking is word overlap. It is a deliberately simple baseline, not a finished retriever.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
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
_STOP = frozenset(
    "the and for you your with that this have from what how should about are was were not but "
    "can will would could into than then them they their there when where which who why".split()
)


@dataclass(frozen=True)
class Result:
    memories: list[Memory]
    withheld: int  # matching memories the owner restricted, counted but never shown


def word_list(text: str) -> list[str]:
    """Content words in the order written, repeats kept."""
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


def words(text: str) -> set[str]:
    return set(word_list(text))


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
