"""Find near-identical memories that were extracted from the same session.

Pure functions, no I/O. Detection is lexical (shared words), so it only catches memories that
are worded almost the same way; paraphrases are left alone on purpose. A false merge is worse
than a missed one, so every rule here leans towards "not a twin":

* only unconfirmed memories, so an owner's decision is never overridden;
* both memories must rest on the same single session, and neither may be assistant-proposed;
* same category and scope;
* the numbers they mention (digits or words like "two") must be equal, and they must agree on
  negation ("not", "never", "doesn't", "avoid" ...);
* the words they share must appear in the same order, so "X over Y" is not "Y over X";
* every word counts, however short ("Go", "C", "JS"), apart from common filler words.

Matching is against one anchor memory per group, never chained, so a group cannot drift into
unrelated memories.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

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


def _features(text: str) -> _Features:
    lowered = text.lower().replace("’", "'")
    negated = bool(_NEGATION.search(lowered))
    words = tuple(_stem(w) for w in _TOKEN.findall(lowered.replace("'", "")) if w not in _FILLER)
    return _Features(words, tuple(sorted(_NUMBER.findall(lowered))), negated)


def _score(a: _Features, b: _Features) -> float:
    if a.numbers != b.numbers or a.negated != b.negated:
        return 0.0
    shared = set(a.words) & set(b.words)
    if len(shared) < MIN_SHARED_WORDS:
        return 0.0
    if [w for w in a.words if w in shared] != [w for w in b.words if w in shared]:
        return 0.0
    return len(shared) / len(set(a.words) | set(b.words))


def similarity(a: str, b: str) -> float:
    """Share of words two texts have in common, from 0 to 1.

    0 when they disagree on numbers or negation, share fewer than MIN_SHARED_WORDS words, or
    use the shared words in a different order.
    """
    return _score(_features(a), _features(b))


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
        ((m, _single_session(m), _features(m.text)) for m in memories if m.state == State.UNCONFIRMED),
        key=lambda item: (item[0].created_at or "", item[0].id),
    )
    eligible = [item for item in eligible if item[1]]
    taken: set[str] = set()
    groups: list[TwinGroup] = []
    for index, (anchor, session, features) in enumerate(eligible):
        if anchor.id in taken:
            continue
        twins = tuple(
            other
            for other, other_session, other_features in eligible[index + 1 :]
            if other.id not in taken
            and other_session == session
            and other.category == anchor.category
            and other.scope == anchor.scope
            and frozenset((anchor.id, other.id)) not in vetoed
            and _score(features, other_features) >= threshold
        )
        if twins:
            taken.update(m.id for m in twins)
            taken.add(anchor.id)
            groups.append(TwinGroup(anchor, twins))
    return groups
