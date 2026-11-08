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
