"""Find near-identical memories that were extracted from the same session.

Pure functions, no I/O. Detection is lexical (shared content words), so it only catches memories
that are worded almost the same way; paraphrases are left alone on purpose. A false merge is worse
than a missed one, so every rule here leans towards "not a twin":

* only unconfirmed memories, so an owner's decision is never overridden;
* both memories must rest on the same single session, and neither may be assistant-proposed;
* same category and scope;
* the numbers they mention (digits or words like "two") must be equal, and they must agree on negation ("not", "never",
  "avoid" ...), because "uses 2 spaces" and "does not use 2 spaces" share nearly every word.

Matching is against one anchor memory per group, never chained, so a group cannot drift into
unrelated memories.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from personakit.model import PROPOSED_BY_ASSISTANT, Memory, State
from personakit.retrieve import word_list

DEFAULT_THRESHOLD = 0.8
MIN_SHARED_WORDS = 3

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|twice|once|half)\b")
_NEGATION = re.compile(
    r"\b(?:not|no|never|none|nor|cannot|without|avoid(?:s|ed)?|dislike[sd]?|hate[sd]?|stop(?:s|ped)?"
    r"|(?:don|doesn|didn|isn|aren|won|wasn|can|shouldn|wouldn)'?t)\b"
)


@dataclass(frozen=True)
class TwinGroup:
    """One memory to keep and the near-identical ones to fold into it."""

    survivor: Memory
    duplicates: tuple[Memory, ...]


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _content(text: str) -> list[str]:
    return [_stem(w) for w in word_list(text)]


def similarity(a: str, b: str) -> float:
    """How alike two texts are, from 0 to 1: the lower of the share of content words they have in
    common and how well those words line up in order (so "unit before integration tests" is not
    the same as "integration before unit tests").

    0 when they disagree on numbers or negation, or share fewer than MIN_SHARED_WORDS words.
    """
    if sorted(_NUMBER.findall(a.lower())) != sorted(_NUMBER.findall(b.lower())):
        return 0.0
    if bool(_NEGATION.search(a.lower())) != bool(_NEGATION.search(b.lower())):
        return 0.0
    left, right = _content(a), _content(b)
    shared = len(set(left) & set(right))
    if shared < MIN_SHARED_WORDS:
        return 0.0
    return min(shared / len(set(left) | set(right)), SequenceMatcher(None, left, right).ratio())


def _single_session(memory: Memory) -> str | None:
    sessions = {e.session_id for e in memory.evidence}
    if len(sessions) != 1 or PROPOSED_BY_ASSISTANT in sessions:
        return None
    return next(iter(sessions))


def find_twins(
    memories: Iterable[Memory],
    threshold: float = DEFAULT_THRESHOLD,
    vetoed: frozenset[frozenset[str]] = frozenset(),
) -> list[TwinGroup]:
    """Group eligible memories into survivor + duplicates.

    `vetoed` holds id pairs the owner already un-merged; they are never proposed again.
    The survivor is the oldest memory in a group, so results do not depend on input order.
    """
    eligible = sorted(
        (m for m in memories if m.state == State.UNCONFIRMED and _single_session(m)),
        key=lambda m: (m.created_at or "", m.id),
    )
    taken: set[str] = set()
    groups: list[TwinGroup] = []
    for index, anchor in enumerate(eligible):
        if anchor.id in taken:
            continue
        twins = tuple(
            other
            for other in eligible[index + 1 :]
            if other.id not in taken
            and _single_session(other) == _single_session(anchor)
            and other.category == anchor.category
            and other.scope == anchor.scope
            and frozenset((anchor.id, other.id)) not in vetoed
            and similarity(anchor.text, other.text) >= threshold
        )
        if twins:
            taken.update(m.id for m in twins)
            taken.add(anchor.id)
            groups.append(TwinGroup(anchor, twins))
    return groups
