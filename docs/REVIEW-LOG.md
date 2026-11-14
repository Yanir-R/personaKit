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
| `personakit/decay.py`, `tidy.py`; `store.py`, `model.py`, `mcp_server.py`, `cli.py` (changes) | 2026-11-14 | none; migration 3 adds `last_seen_at`; an assistant proposal cannot revive or refresh a memory. Checked on a copy of a real store: upgrade, archive, undo and reads behave as documented | clean |
| `tests/test_decay.py`, `test_store_decay.py`, `test_tidy.py`; `test_cli.py`, `test_mcp_server.py` (changes) | 2026-11-14 | invented sentences only | clean |
| `personakit/digest.py`, `tests/test_digest.py`; `store.py`, `cli.py` (changes) | 2026-11-14 | none; local output only, text without quotes; invented test data | clean |
| `personakit/twins.py`; `store.py`, `tidy.py`, `digest.py`, `cli.py`, `model.py`, `review.py`, `mcp_server.py`, `retrieve.py` (changes) | 2026-11-14 | none; written for this repository, word-based only, thresholds chosen from invented examples. Migration 4 adds `merged_into` and `merge_vetoes`; a folded memory keeps its own rows, so forget leaves nothing behind. Security and code review findings fixed, each with a regression test | clean |
| `tests/test_twins.py`, `test_merge_store.py`; `test_tidy.py`, `test_cli.py`, `test_digest.py` (changes) | 2026-11-14 | invented sentences only | clean |
