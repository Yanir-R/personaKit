"""MCP server: lets an assistant read the owner's memories and propose new ones.

Assistants can never approve, restrict, hide or forget. Only the owner does that, in `review`.
The functions below hold the logic and need no MCP package; `build_server` wraps them.
Install the optional dependency with: pip install "personakit[mcp]"
"""

from __future__ import annotations

from personakit import extract, retrieve
from personakit.model import PROPOSED_BY_ASSISTANT, Evidence, Memory, State
from personakit.store import Store

NOTE_UNCONFIRMED = "Unconfirmed: extracted from the owner's conversations but not yet reviewed by them."
NOTE_SEEN = "Entries marked seen were sent earlier in this session. If you no longer have them, ask again with include_seen."
EVIDENCE_QUOTES = 2


def read_memories(
    store: Store,
    question: str,
    limit: int = 7,
    relevance: retrieve.Relevance = retrieve.overlap,
    context: str = "",
    scope: str = "",
    include_evidence: bool = False,
    include_seen: bool = False,
    seen: set[str] | None = None,
) -> dict:
    """Memories relevant to a question, under the one read policy.

    `seen` holds the ids already sent in full during this session. A memory in it comes back as
    its id only, unless `include_seen`, or `include_evidence` (the quotes would be new). Ids sent
    in full are added to it. With no set, every memory is sent in full.
    """
    limit = max(1, min(limit, 20))
    result = retrieve.search(store.list(), question, limit, relevance, context, scope)
    store.log_read(len(result.memories), result.withheld)
    items, full = [], []
    for m in result.memories:
        if seen is not None and m.id in seen and not (include_seen or include_evidence):
            items.append({"id": m.id, "seen": True})
            continue
        item = {"id": m.id, "text": m.text, "category": m.category, "confirmed": m.state == State.APPROVED}
        if include_evidence:
            item["evidence"] = [retrieve.served_quote(e.quote) for e in m.evidence[:EVIDENCE_QUOTES]]
        items.append(item)
        full.append(m)
        if seen is not None:
            seen.add(m.id)
    response = {"memories": items, "withheld": result.withheld, "more": result.more}
    if any(m.state != State.APPROVED for m in full):
        response["note"] = NOTE_UNCONFIRMED
    if len(full) < len(items):
        response["seen_note"] = NOTE_SEEN
    return response


def propose_memory(store: Store, text: str, quote: str, category: str = "other") -> dict:
    """Suggest a memory. It is stored unconfirmed and marked as assistant-proposed.

    The quote is whatever the assistant supplies and cannot be verified here, so the review screen
    labels these proposals.
    """
    problem = extract.text_problem(text) or ("empty_quote" if not quote.strip() else None)
    if problem:
        return {"stored": False, "reason": problem}
    memory = Memory(
        text=text.strip(),
        category=category if category in extract.CATEGORIES else "other",
        evidence=(Evidence(PROPOSED_BY_ASSISTANT, 0, extract.quote_of(quote.strip())),),
    )
    created = store.add(memory, observed=False)
    return {"stored": True, "id": memory.id, "new": created, "state": State.UNCONFIRMED.value}


def build_server(store: Store, relevance: retrieve.Relevance = retrieve.overlap):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise SystemExit('The MCP server needs the "mcp" package: pip install "personakit[mcp]"') from exc

    server = FastMCP("personakit")

    # One server process serves one assistant session, so what it has already sent lives here,
    # in memory only. It is never written to the store.
    sent: set[str] = set()

    @server.tool()
    def personakit_read(
        question: str,
        context: str = "",
        scope: str = "",
        limit: int = 7,
        include_evidence: bool = False,
        include_seen: bool = False,
    ) -> dict:
        """Read what the owner has said that is relevant to one focused question.

        Ask before you act, one focused question at a time, and say in `context` what you are
        about to do. An empty `memories` list means nothing relevant is known. `more` counts
        relevant memories left out by `limit`. Unconfirmed memories are labelled and may be wrong.
        An entry with only `seen: true` was sent earlier in this session; if you no longer have
        it, ask again with include_seen. Ask for evidence only when you need the owner's own words.
        `scope` (optional) limits the read to one project's memories plus general ones.
        """
        return read_memories(store, question, limit, relevance, context, scope, include_evidence, include_seen, sent)

    @server.tool()
    def personakit_propose(text: str, quote: str, category: str = "other") -> dict:
        """Suggest a memory about the owner, with the owner's own words that support it."""
        return propose_memory(store, text, quote, category)

    return server


def serve(store: Store, relevance: retrieve.Relevance = retrieve.overlap) -> None:
    build_server(store, relevance).run()
