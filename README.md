<p align="center">
  <img src="docs/assets/logo.svg" width="96" alt="PersonaKit logo">
</p>

<h1 align="center">PersonaKit</h1>

<p align="center">
  <strong>Your AI's memory. Your say.</strong><br>
  Memory for your AI assistants that you can read, correct and take with you.
</p>

<p align="center">
  <a href="https://github.com/Yanir-R/personaKit/actions/workflows/tests.yml"><img src="https://github.com/Yanir-R/personaKit/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/MCP-server-b94f30.svg" alt="MCP server">
  <img src="https://img.shields.io/badge/status-pre--release-orange.svg" alt="Status: pre-release">
</p>

<p align="center">
  <img src="docs/assets/demo.gif" width="760" alt="Terminal demo: personakit sweep, review, list and serve, with example data">
</p>

PersonaKit reads the conversations you already have with your assistants, proposes short
memories ("you prefer direct, practical feedback"), keeps the exact quote each one came from,
and serves only what you allow back to your assistants over MCP. Everything runs on your own
machine. There is no PersonaKit server and no account.

> **Status: pre-release (0.1 in progress).** This repository is being built in public.
> See [docs/ROADMAP.md](docs/ROADMAP.md) for what exists and what is planned.

## Why PersonaKit

- **Every memory has a receipt.** Each memory is stored with the quote it came from, in your
  own words, so you can see why your assistant believes something about you.
- **You have the last word.** Approve, restrict, hide or forget any memory. Restricted
  memories are never served. Assistants can read and propose, but only you can decide.
- **Local by design.** One SQLite file on your machine. No account, no PersonaKit server,
  no telemetry. Extraction uses a model you already use, and sends it only the turns you wrote.
- **Small enough to read.** A short pure-Python core with no required dependencies, so you
  can check what it does before you trust it with your conversations.

## Quickstart

Requires Python 3.10+ and a signed-in `claude` or `codex` CLI for extraction.

```sh
git clone https://github.com/Yanir-R/personaKit.git
cd personaKit
pip install -e ".[mcp]"

personakit sweep --cli claude --model <model-name> --max-calls 20   # read sessions, extract memories
personakit review                                                    # optional: approve, restrict, hide, forget
personakit list                                                      # see what is stored
personakit stats                                                     # counts only, never memory text
personakit serve                                                     # MCP server over stdio for your assistants
```

`sweep`, `list` and `stats` also take `--json` for stable, sorted machine-readable output.

The model name is always yours to choose. Nothing leaves your machine except the turns you wrote,
sent to the model you named. See [docs/PRIVACY.md](docs/PRIVACY.md).

## Connect your assistant

`personakit serve` is a standard MCP server over stdio, so any client that can launch a local
MCP server can use it.

**Claude Code**

```sh
claude mcp add personakit -- personakit serve
```

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.personakit]
command = "personakit"
args = ["serve"]
```

Your assistant gets two tools:

| Tool | What it does |
|---|---|
| `personakit_read` | Returns the memories relevant to a question, each with its evidence quotes and whether you have confirmed it. |
| `personakit_propose` | Lets the assistant suggest a new memory. It is stored as *unconfirmed* until you review it. |

## How it works

```mermaid
flowchart LR
  A[Claude Code / Codex sessions] --> B[ingest]
  B -->|your own words only| C[extract]
  C --> D[(local SQLite store)]
  D --> E[review CLI, optional]
  D --> F[MCP server]
  F --> G[your assistants]
```

1. **Ingest** reads local session files. Only the turns you wrote leave the parsing step.
2. **Extract** asks a model you already use (your own CLI login or API key) to propose memories.
3. **Store** keeps each memory with its source quote, a state, and a scope.
4. **Review** is optional. Memories you never review are served marked *unconfirmed*; you
   can approve, restrict, hide or forget any of them at any time.
5. **Serve** exposes the store to assistants over MCP, with the evidence attached.

A memory is always in one of four states:

| State | Served to assistants? |
|---|---|
| `unconfirmed` (default) | Yes, labelled as unconfirmed |
| `approved` | Yes |
| `restricted` | Never |
| `archived` | Never |

## What works today

| | Status |
|---|---|
| Claude Code sessions | Available in 0.1 |
| Codex sessions | Available in 0.1 |
| Any MCP client (read and propose) | Available in 0.1 |
| ChatGPT, claude.ai and Gemini export import | Planned for 0.3 |

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the design, module by module.
- [docs/PRIVACY.md](docs/PRIVACY.md): exactly what is sent where.
- [docs/ROADMAP.md](docs/ROADMAP.md): what exists and what is planned.

## Contributing

Issues and small pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first;
commits are signed off under the [DCO](DCO). To report a security problem, see
[SECURITY.md](SECURITY.md).

## License

Apache-2.0. See [LICENSE](LICENSE). The PersonaKit name and logo are covered by
[TRADEMARK.md](TRADEMARK.md).
