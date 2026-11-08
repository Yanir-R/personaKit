"""Claude Code adapter: reads ~/.claude/projects/<project>/<session>.jsonl.

In this format a tool result is stored as a record of type "user", so the record type
alone says nothing about who wrote it. A record counts as the owner's only when it is a
top-level user record that is not a tool result, not client bookkeeping, and not a
sidechain (a subagent transcript whose "user" turns were written by the parent agent).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from personakit.ingest.common import clean_text, in_sandbox, read_jsonl
from personakit.model import Session, Turn

SOURCE = "claude-code"

# A user record starting with one of these is the client talking, not the owner.
ENVELOPES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command",
    "<bash-",
    "<task-notification>",
    "<user-prompt-submit-hook>",
    "<system-reminder>",
    "Caveat:",
    "[Request interrupted",
    "API Error",
)

# Origins the client stamps on user records it delivered itself.
_HARNESS_ORIGINS = ("peer", "task-notification")
_HUMAN_ORIGIN = "human"
_HEADLESS_ENTRYPOINT = "sdk-cli"


def default_root() -> Path:
    return Path.home() / ".claude" / "projects"


def discover(root: Path | None = None) -> list[Path]:
    """Session files exactly two levels deep: <root>/<project>/<session>.jsonl.

    Never recursive: a recursive search would admit subagent transcripts.
    """
    root = root or default_root()
    if not root.is_dir():
        return []
    found = []
    for project in sorted(root.iterdir()):
        if project.is_dir():
            found.extend(sorted(p for p in project.glob("*.jsonl") if p.is_file()))
    return found


def read_session(path: Path) -> Session:
    dropped: Counter = Counter()
    records = list(read_jsonl(path, dropped))
    session = Session(source=SOURCE, session_id=path.stem, dropped=dropped)

    if _is_machine_session(records):
        dropped["machine_session"] += 1
        return session

    for record in records:
        if record.get("type") != "user":
            continue
        reason = _drop_reason(record)
        text = None
        if reason is None:
            text, reason = clean_text(_visible_text(record), ENVELOPES)
        if text is None:
            dropped[reason] += 1
            continue
        session.turns.append(
            Turn(
                source=SOURCE,
                session_id=session.session_id,
                index=len(session.turns),
                timestamp=record.get("timestamp"),
                text=text,
            )
        )
    return session


def _is_machine_session(records: list[dict]) -> bool:
    """A headless run, or one started inside PersonaKit's own extraction sandbox.

    A headless run has exactly one user record, the prompt a pipeline wrote. It counts as
    the owner's only if the client stamped some user record as human.
    """
    if any(in_sandbox(r.get("cwd")) for r in records):
        return True
    entrypoints = {r["entrypoint"] for r in records if isinstance(r.get("entrypoint"), str)}
    if _HEADLESS_ENTRYPOINT not in entrypoints:
        return False
    return not any(_origin_kind(r) == _HUMAN_ORIGIN for r in records if r.get("type") == "user")


def _origin_kind(record: dict) -> str | None:
    origin = record.get("origin")
    return origin.get("kind") if isinstance(origin, dict) else None


def _drop_reason(record: dict) -> str | None:
    if record.get("isSidechain"):
        return "sidechain"
    content = record.get("message", {}).get("content")
    has_result_block = isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )
    if record.get("toolUseResult") is not None or has_result_block:
        return "tool_result"
    if record.get("isMeta") is True or record.get("isCompactSummary") is True:
        return "harness"
    if _origin_kind(record) in _HARNESS_ORIGINS:
        return "harness"
    return None


def _visible_text(record: dict) -> str:
    """Only text blocks: an image block is a screenshot of whatever was on screen."""
    content = record.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
