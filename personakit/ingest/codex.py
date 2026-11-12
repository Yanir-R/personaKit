"""Codex CLI adapter: reads ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.

Reads only rollout files. Nothing else under ~/.codex is opened: that directory can hold
credentials, and it is never written to.

A subagent rollout begins with a replay of its parent's transcript. Those turns were
already counted in the parent's own rollout, so records before the replay cut are
dropped; records at or after it belong to the subagent and are kept.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from personakit.ingest.common import append_turn, clean_text, in_sandbox, read_jsonl
from personakit.model import Session

SOURCE = "codex-cli"

# A user message starting with one of these is context the client injected.
ENVELOPES = (
    "<environment_context>",
    "<recommended_plugins>",
    "<image name=",
    "# AGENTS.md instructions",
    "The following is the Codex agent",
)


def default_root() -> Path:
    return Path.home() / ".codex" / "sessions"


def discover(root: Path | None = None) -> list[Path]:
    """Rollout files exactly three directories down (year/month/day)."""
    root = root or default_root()
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*/*/*/rollout-*.jsonl") if p.is_file())


def read_session(path: Path) -> Session:
    dropped: Counter = Counter()
    records = list(read_jsonl(path, dropped))
    meta = _session_meta(records)
    session = Session(source=SOURCE, session_id=meta["id"] or _id_from_name(path), dropped=dropped)

    if in_sandbox(meta["cwd"]):
        dropped["machine_session"] += 1
        return session

    for record in records:
        payload = record.get("payload") or {}
        if record.get("type") != "response_item" or payload.get("type") != "message":
            continue
        if payload.get("role") != "user":
            continue
        reason = _replay_reason(meta, record)
        text = None
        if reason is None:
            text, reason = clean_text(_input_text(payload), ENVELOPES)
        if text is None:
            dropped[reason] += 1
            continue
        append_turn(session, text, record.get("timestamp"))
    return session


def _id_from_name(path: Path) -> str:
    name = path.stem
    return name[len("rollout-"):] if name.startswith("rollout-") else name


def _session_meta(records: list[dict]) -> dict:
    """File-level facts from session_meta records. A subagent is detected by the presence of
    the "subagent" key: the source field is a tagged union and that arm has no "type"."""
    meta = {"id": None, "cwd": None, "subagent": False, "replay_cut": None}
    for record in records:
        if record.get("type") != "session_meta":
            continue
        payload = record.get("payload") or {}
        meta["id"] = meta["id"] or payload.get("id")
        meta["cwd"] = meta["cwd"] or payload.get("cwd")
        source = payload.get("source")
        if isinstance(source, dict) and "subagent" in source:
            meta["subagent"] = True
        if payload.get("subagent_history_start_ordinal") is not None:
            meta["replay_cut"] = payload["subagent_history_start_ordinal"]
    return meta


def _replay_reason(meta: dict, record: dict) -> str | None:
    if not meta["subagent"]:
        return None
    ordinal = record.get("ordinal")
    if ordinal is None or meta["replay_cut"] is None:
        return "subagent_unplaceable"
    if ordinal < meta["replay_cut"]:
        return "subagent_replayed_history"
    return None


def _input_text(payload: dict) -> str:
    """Text of input_text blocks. Image blocks carry no text and are ignored."""
    blocks = payload.get("content") or []
    return "".join(
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "input_text"
    )
