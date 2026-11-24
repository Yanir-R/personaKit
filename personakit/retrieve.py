"""Which memories an assistant may see, and which ones answer a question.

This is the one read policy. The MCP server uses it, and so does anything else that shows memories
to an assistant. Approved and unconfirmed memories are served (unconfirmed ones are labelled as
such); restricted and archived memories are never served.

Only relevant memories are served: when nothing matches, the answer is empty. Ranking is word
overlap. It is a deliberately simple baseline, not a finished retriever.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from personakit.model import Memory, State

SERVED = (State.APPROVED, State.UNCONFIRMED)

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
    more: int = 0  # further relevant, servable memories left out by the limit


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP_WORDS}


def about(memory: Memory) -> str:
    """Everything a memory is about: its text, category and the owner's own hints."""
    return " ".join((memory.text, memory.category, *memory.answers, *memory.applies_when))


def overlap(question: str, memories: Sequence[Memory]) -> list[float]:
    """The built-in relevance: how many words of the question each memory shares."""
    asked = words(question)
    return [float(len(asked & words(about(m)))) for m in memories]


Relevance = Callable[[str, Sequence[Memory]], Sequence[float]]
# (question, context, the relevant servable memories best first, the assistant's name) -> the ones
# to serve, or None to leave the read as it is. It may only narrow: see `search`.
Select = Callable[[str, str, Sequence[Memory], str], "Sequence[Memory] | None"]


def search(
    memories: Iterable[Memory],
    question: str,
    limit: int = 7,
    relevance: Relevance = overlap,
    context: str = "",
    scope: str = "",
    select: Select | None = None,
    client: str = "",
) -> Result:
    """Apply the read policy. `relevance` only orders memories (above 0 means relevant); what may
    be served is decided here and cannot be widened by it.

    `context` is what the assistant is about to do. It is scored like a second question and a
    memory keeps the better of its two scores, so the hook itself never changes. With a `scope`,
    only memories of that scope or "global" ones are considered at all.

    `select`, when given, sees only the memories that may be served and are relevant, best first,
    once per read, with the question, the context and the assistant's name (`client`, "" when
    unknown). It may only narrow them: whatever it returns that was not offered is ignored, the
    order stays this one, and None leaves the read unchanged. Restricted and archived memories
    never reach it.
    """
    memories = [m for m in memories if not scope or m.scope in ("global", scope)]
    scores = list(relevance(question, memories))
    if context.strip():
        scores = [max(a, b) for a, b in zip(scores, relevance(context, memories), strict=True)]
    scored, withheld = [], 0
    for memory, score in zip(memories, scores, strict=True):
        if score <= 0:
            continue
        if memory.state == State.RESTRICTED:
            withheld += 1
        elif memory.state in SERVED:
            scored.append((score, memory))

    # Most relevant first; approved before unconfirmed; then oldest first for a stable order.
    scored.sort(key=lambda s: (-s[0], s[1].state != State.APPROVED, s[1].created_at or "", s[1].id))
    ranked = [memory for _, memory in scored]
    if select is not None and ranked:
        picked = select(question, context, tuple(ranked), client)
        if picked is not None:
            keep = {m.id for m in picked}
            ranked = [m for m in ranked if m.id in keep]
    chosen = ranked[:limit]
    return Result(chosen, withheld, len(ranked) - len(chosen))


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
