# Architecture (v0.2 design)

PersonaKit is a small local pipeline with one database. Each stage has one job and talks to
the next only through the store.

```mermaid
flowchart TB
  subgraph Sources
    CC[Claude Code sessions]
    CX[Codex sessions]
  end
  subgraph Pipeline
    IN[ingest/ adapters]
    EX[extract: prompt + parse]
    LLM[llm: BYO model client]
    ST[(store: SQLite)]
    RV[review: CLI]
    MCP[mcp_server]
    SS[stats: local counts]
    TD[tidy: decay, on request]
  end
  CC --> IN
  CX --> IN
  IN -->|Turn: owner text only| EX
  EX <--> LLM
  EX -->|proposed Memory + Evidence| ST
  ST <--> RV
  ST --> MCP
  ST --> SS
  ST <--> TD
  MCP --> AS[Assistants]
```

## Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `model` | Plain data types: `Turn`, `Session`, `Memory`, `Evidence`, `State`, `Decider`. No I/O. | nothing |
| `ingest/` | One adapter per source (`claude_code`, `codex`) plus `common` for the rules they share. Reads a session file, returns the owner's `Turn`s with a count of what was dropped and why. | `model` |
| `llm` | One interface, `complete(prompt) -> str`, implemented by two CLI-backed clients (`claude`, `codex`). The per-run call budget lives here. | nothing |
| `extract` | Builds the prompt from owner turns, validates the reply into `Memory` + `Evidence`, and counts what it rejects and why. | `model`, `llm` |
| `sweep` | Runs ingest, extract and store over new sessions. Skips unchanged files, stops only on budget or model error, never because unreviewed memories are piling up. | `ingest`, `extract`, `llm`, `store` |
| `retrieve` | The one read policy: approved and unconfirmed memories are served, restricted and archived never are. It also shapes the evidence quotes an assistant receives (email addresses masked, cut at a word boundary). Word-overlap ranking, a baseline to be measured. | `model` |
| `store` | The only module that touches SQLite. Schema, migrations, queries, state changes. | `model` |
| `review` | Terminal UI over the store: approve, restrict, hide, forget. Optional by design. | `store` |
| `mcp_server` | Two tools for assistants: `personakit_read` and `personakit_propose`. Holds no read-policy constants of its own. Assistants cannot approve, restrict, hide or forget; only the owner can, in `review`. | `store`, `retrieve`, `extract` |
| `decay` | Finds unconfirmed memories not seen again for a long time (90 days by default). Pure functions. | `model` |
| `tidy` | Turns `decay` into a plan (read-only), applies it only on request, and reverses single steps. | `decay`, `store` |
| `stats` | Counts only (memories by state, sessions extracted, reads and how many returned something). Never content. | `store` |
| `cli` | Argument parsing and wiring; no logic. | all |

One rule keeps the layering honest: **only `store` imports `sqlite3`, only `llm` talks to a
model, only `ingest` reads session files.** A second implementation of any of those is a bug.

## Data model

- **Turn**: `(source, session_id, index, timestamp, text)`. Only owner-authored turns exist here.
- **Memory**: `id, text, category, scope, state, created_at, last_seen_at, decided_at, decided_by`.
  `last_seen_at` moves forward each time the same statement is extracted again.
- **Evidence**: `memory_id, session_id, turn_index, quote`. Every memory has at least one.
- **State**: `unconfirmed` (default, served with a label) -> `approved` | `restricted` |
  `archived`. Nothing is ever hard-deleted without an explicit `forget` by the owner.

## Policy

1. A memory with no evidence is not stored.
2. Unconfirmed memories are served, labelled as unconfirmed. Review is a quality tool, not a gate.
3. The system never deletes a memory, and never touches a memory you have decided on. Extracting
   the same statement again adds evidence to the existing memory and leaves your decision alone.
   One thing changes unconfirmed memories, and only when you run `personakit tidy --apply` (the
   default is a plan that changes nothing): archiving memories not seen again for 90 days. It is
   reversible with `personakit undo <id>`, and a memory that decay archived comes back by itself
   if the statement is extracted again from your own words. An assistant proposing the same text
   does not bring it back and does not reset its age.
4. Only text the owner wrote is sent to a model.
5. Statistics are counts, never content, and are local unless the owner chooses to share them.

## Out of scope for now

Hosted service, accounts, sync, ChatGPT/Gemini/claude.ai import and third-party name detection.
See the roadmap for what is planned.

## Limits in 0.2

Decay looks only at how long ago a statement was last extracted, not at whether it is still true.
