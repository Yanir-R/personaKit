"""Rules shared by every source adapter: reading JSONL and deciding what the owner wrote."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterator

# A turn that is mostly one long unbroken token is a pasted path, hash or key, not speech.
# Shape only, never meaning, so the rule cannot be tuned to select interesting text.
PASTE_MIN_TOKEN = 32
PASTE_SHARE = 0.5

_INJECTED_BLOCK = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)

# Directory-name prefix PersonaKit's own extraction runs under. Sessions started there
# contain prompts written by PersonaKit, not by the owner, and are always skipped.
SANDBOX_PREFIX = "personakit-extract-"


def read_jsonl(path: Path, dropped: Counter) -> Iterator[dict]:
    """Yield each parsed JSON object in a file. Lines that do not parse are counted, not hidden."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                dropped["unparsable_line"] += 1
                continue
            if isinstance(record, dict):
                yield record


def is_paste(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return True
    longest = max(len(token) for token in tokens)
    return longest >= PASTE_MIN_TOKEN and longest / len(text) > PASTE_SHARE


def in_sandbox(cwd: object) -> bool:
    """True when a session's working directory is one PersonaKit's extraction created."""
    if not isinstance(cwd, str):
        return False
    return any(part.startswith(SANDBOX_PREFIX) for part in Path(cwd).parts)


def clean_text(text: str, envelopes: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Return (text, None) if the owner wrote it, else (None, reason it was dropped).

    Injected blocks are removed before the envelope check, so a reminder followed by
    a real sentence keeps the sentence.
    """
    stripped = _INJECTED_BLOCK.sub("", text).strip()
    if not stripped:
        return None, "empty_or_injected"
    if stripped.startswith(envelopes):
        return None, "scaffolding"
    if is_paste(stripped):
        return None, "paste"
    return stripped, None
