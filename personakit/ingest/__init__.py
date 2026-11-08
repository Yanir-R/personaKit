"""Source adapters. Each module exposes SOURCE, default_root(), discover() and read_session().

Adapters are the only code that reads session files, and they return only what the owner wrote.
"""

from personakit.ingest import claude_code, codex

ADAPTERS = {adapter.SOURCE: adapter for adapter in (claude_code, codex)}

__all__ = ["ADAPTERS", "claude_code", "codex"]
