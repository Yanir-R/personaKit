"""Find near-identical memories, whichever sessions they were extracted from.

Pure functions, no I/O. Detection is lexical (shared words), so it only catches memories that
are worded almost the same way; paraphrases are left alone on purpose. A false merge is worse
than a missed one, so every rule here leans towards "not a twin":

* only unconfirmed memories, so an owner's decision is never overridden;
* neither may rest on an assistant's proposal;
* same category and scope;
* the numbers they mention (digits or words like "two") must be equal, and they must agree on
  negation ("not", "never", "doesn't", "avoid" ...). This holds whatever scores the pair;
* the words they share must appear in the same order, so "X over Y" is not "Y over X";
* every word counts, however short ("Go", "C", "JS"), apart from common filler words.

Matching is against one anchor memory per group, never chained, so a group cannot drift into
unrelated memories.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache

from personakit.model import PROPOSED_BY_ASSISTANT, Memory, State
from personakit.retrieve import STOP_WORDS

DEFAULT_THRESHOLD = 0.8
MIN_SHARED_WORDS = 3

_TOKEN = re.compile(r"[a-z0-9+#]+")
_FILLER = STOP_WORDS | frozenset("a an as at be by do i in is it me my of on or to we".split())
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|twice|once|half)\b")
_NEGATION = re.compile(
    r"\b(?:not|no|never|none|nor|cannot|without|avoid(?:s|ed)?|dislike[sd]?|hate[sd]?|stop(?:s|ped)?"
    r"|\w+n't|(?:don|doesn|didn|isn|aren|won|wasn|weren|can|couldn|shouldn|wouldn|hasn|haven|hadn)t)\b"
)


@dataclass(frozen=True)
class TwinGroup:
    """One memory to keep and the near-identical ones to fold into it."""

    survivor: Memory
    duplicates: tuple[Memory, ...]


@dataclass(frozen=True)
class _Features:
    """What similarity compares, computed once per memory."""

    words: tuple[str, ...]
    numbers: tuple[str, ...]
    negated: bool


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


@lru_cache(maxsize=4096)
def _features(text: str) -> _Features:
    lowered = text.lower().replace("’", "'")
    negated = bool(_NEGATION.search(lowered))
    words = tuple(_stem(w) for w in _TOKEN.findall(lowered.replace("'", "")) if w not in _FILLER)
    return _Features(words, tuple(sorted(_NUMBER.findall(lowered))), negated)


def agree(a: str, b: str) -> bool:
    """Whether two texts mention the same numbers and agree on negation."""
    left, right = _features(a), _features(b)
    return left.numbers == right.numbers and left.negated == right.negated


def similarity(a: str, b: str) -> float:
    """The built-in similarity: share of words two texts have in common, from 0 to 1.

    0 when they disagree on numbers or negation, share fewer than MIN_SHARED_WORDS words, or
    use the shared words in a different order.
    """
    if not agree(a, b):
        return 0.0
    left, right = _features(a), _features(b)
    shared = set(left.words) & set(right.words)
    if len(shared) < MIN_SHARED_WORDS:
        return 0.0
    if [w for w in left.words if w in shared] != [w for w in right.words if w in shared]:
        return 0.0
    return len(shared) / len(set(left.words) | set(right.words))


Similarity = Callable[[str, str], float]


def _eligible(memory: Memory) -> bool:
    return memory.state == State.UNCONFIRMED and all(e.session_id != PROPOSED_BY_ASSISTANT for e in memory.evidence)


def find_twins(
    memories: Iterable[Memory],
    threshold: float = DEFAULT_THRESHOLD,
    vetoed: frozenset[frozenset[str]] = frozenset(),
    similarity: Similarity = similarity,
) -> list[TwinGroup]:
    """Group eligible memories into survivor + duplicates.

    `similarity` only scores a pair of texts. Which memories are eligible, and that a pair must
    agree on numbers and negation, is decided here.

    `vetoed` holds id pairs the owner already un-merged; they are never proposed again.
    The survivor is the oldest memory in a group, so results do not depend on input order.
    """
    def age(memory: Memory) -> tuple[str, str]:
        return (memory.created_at or "", memory.id)

    # Only memories of one category and scope are ever compared, so bucket them first.
    buckets: dict[tuple[str, str | None], list[Memory]] = {}
    for memory in sorted(filter(_eligible, memories), key=age):
        buckets.setdefault((memory.category, memory.scope), []).append(memory)
    groups: list[TwinGroup] = []
    for bucket in buckets.values():
        taken: set[str] = set()
        for index, anchor in enumerate(bucket):
            if anchor.id in taken:
                continue
            twins = tuple(
                other
                for other in bucket[index + 1 :]
                if other.id not in taken
                and frozenset((anchor.id, other.id)) not in vetoed
                and agree(anchor.text, other.text)
                and similarity(anchor.text, other.text) >= threshold
            )
            if twins:
                taken.update(m.id for m in twins)
                groups.append(TwinGroup(anchor, twins))
    return sorted(groups, key=lambda group: age(group.survivor))
