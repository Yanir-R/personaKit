# File review log

Before a file enters this repository it is read line by line for: personal data, private
paths or hostnames, internal ticket or decision references, working-method details, and
duplicated logic. Each entry records the result.

| File | Reviewed | Findings | Result |
|---|---|---|---|
| `personakit/model.py` | 2026-11-08 | none | clean |
| `personakit/ingest/common.py` | 2026-11-08 | none; sandbox prefix is a public constant | clean |
| `personakit/ingest/claude_code.py` | 2026-11-08 | none; no paths or usernames kept on a Turn | clean |
| `personakit/ingest/codex.py` | 2026-11-08 | none; reads only rollout files | clean |
| `personakit/store.py` | 2026-11-08 | none; only module importing sqlite3 | clean |
| `tests/fixtures/**` | 2026-11-08 | invented sentences and `/work/acme` paths only | clean |
| `tests/*.py` | 2026-11-08 | none | clean |
| `personakit/llm.py` | 2026-11-08 | none; prompt travels on stdin, run in an empty marked sandbox. CLI argument lists not yet run against real CLIs | clean, needs live check |
| `personakit/extract.py` | 2026-11-08 | none; prompt is generic, rejects credential-shaped text | clean |
| `personakit/sweep.py` | 2026-11-08 | none | clean |
| `tests/test_llm.py`, `test_extract.py`, `test_sweep.py`, `helpers.py` | 2026-11-08 | none; hygiene check caught a key-shaped test string, now built at runtime | clean |
| `personakit/retrieve.py` | 2026-11-08 | none | clean |
| `personakit/review.py` | 2026-11-08 | none | clean |
| `personakit/stats.py` | 2026-11-08 | none; counts only | clean |
| `personakit/mcp_server.py` | 2026-11-08 | none; assistants get read and propose only. Verified with a real stdio MCP client against mcp 1.30 | clean |
| `personakit/cli.py` | 2026-11-08 | none | clean |
| `personakit/store.py` (changes) | 2026-11-08 | added `reads` table via migration 2; list order now insertion order | clean |
| `personakit/extract.py` (changes) | 2026-11-08 | shared text checks moved into `text_problem` so extraction and assistant proposals use one rule | clean |
| `tests/*` (new) | 2026-11-08 | invented data; a key-shaped string is assembled at runtime | clean |
| `personakit/plugins.py`, `docs/PLUGINS.md`, `tests/test_plugins.py`; `retrieve.py`, `mcp_server.py`, `cli.py` (changes) | 2026-11-14 | none; opt-in by name, scoring only, a policy test proves a plugin cannot widen what is served | clean |
