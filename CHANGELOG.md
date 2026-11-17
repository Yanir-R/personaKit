# Changelog

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
