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


def read_memories(store: Store, question: str, limit: int = 7) -> dict:
    """Memories relevant to a question, under the one read policy."""
    limit = max(1, min(limit, 20))
    result = retrieve.search(store.list(), question, limit)
    store.log_read(len(result.memories), result.withheld)
    response = {
        "memories": [
            {
                "id": m.id,
                "text": m.text,
                "category": m.category,
                "confirmed": m.state == State.APPROVED,
                "evidence": [retrieve.served_quote(e.quote) for e in m.evidence[:2]],
            }
            for m in result.memories
        ],
        "withheld": result.withheld,
    }
    if any(m.state != State.APPROVED for m in result.memories):
        response["note"] = NOTE_UNCONFIRMED
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
    created = store.add(memory)
    return {"stored": True, "id": memory.id, "new": created, "state": State.UNCONFIRMED.value}


def build_server(store: Store):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise SystemExit('The MCP server needs the "mcp" package: pip install "personakit[mcp]"') from exc

    server = FastMCP("personakit")

    @server.tool()
    def personakit_read(question: str, limit: int = 7) -> dict:
        """Read the owner's memories relevant to a question. Unconfirmed ones are labelled."""
        return read_memories(store, question, limit)

    @server.tool()
    def personakit_propose(text: str, quote: str, category: str = "other") -> dict:
        """Suggest a memory about the owner, with the owner's own words that support it."""
        return propose_memory(store, text, quote, category)

    return server


def serve(store: Store) -> None:
    build_server(store).run()
