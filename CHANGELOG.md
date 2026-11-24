# Changelog

## Unreleased

- `personakit_read` returns only relevant memories. When nothing is relevant the answer is
  empty: approved memories are no longer added as standing context.
- Evidence quotes are sent only with `include_evidence`. A memory already sent by the same
  server process comes back as its id with `seen: true`, unless `include_seen`.
- Reads take `context` (what the assistant is about to do, ranked like a second question) and
  `scope` (that scope plus global). `more` in the answer counts relevant memories left out by
  the limit.
- Owner-written `answers` and `applies_when` on a memory, set with `personakit hints`. They
  help ranking and are never sent to assistants. Existing stores upgrade in place.
- A third extension point, `select`: once per read, after the read policy, a plugin may narrow
  the relevant servable memories to fewer. It cannot add memories or change their order, and
  never sees restricted or archived ones. It is told the name the assistant connected with.

## 0.2.0

- `personakit tidy`: a plan that folds near-identical unconfirmed memories into the oldest one
  and archives unconfirmed memories that went stale. Nothing changes without `--apply`, and
  `personakit undo <id>` reverses either.
- `personakit digest`: what changed in the last days, printed locally.
- Extension points for two scoring functions, relevance and similarity, off unless named in
  `PERSONAKIT_PLUGINS`. Policy stays in the core. See [docs/PLUGINS.md](docs/PLUGINS.md).
- `personakit merges` lists what was folded, and `tidy` and `digest` take `--json`.

## 0.1

- Reads Claude Code and Codex sessions, extracts memories with your own signed-in model CLI,
  stores them in one local SQLite file.
- `personakit review`: approve, restrict, hide or forget memories.
- MCP server (`personakit serve`) for any MCP client: read and propose.
- `personakit stats`: counts only, never memory text. `sweep`, `list` and `stats` take `--json`.
- Served evidence quotes are masked and shortened.
