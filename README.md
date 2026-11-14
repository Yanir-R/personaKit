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

> **Status: pre-release (0.2 in progress).** This repository is being built in public.
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
personakit tidy                                                      # plan: fold same-session twins, archive stale memories
personakit tidy --apply                                              # carry the plan out (reverse any with `personakit undo <id>`)
personakit digest                                                    # what changed in the last 7 days (local, prints memory text)
personakit serve                                                     # MCP server over stdio for your assistants
personakit forget <memory-id>                                        # delete a memory and its quotes for good
```

`sweep`, `list`, `stats`, `tidy` and `digest` also take `--json` for stable, sorted machine-readable output.

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

<p align="center">
  <img src="docs/assets/how-it-works.svg" width="760" alt="How PersonaKit works: session files are read on your machine, only the turns you wrote go to the model you chose, memories are stored in a local SQLite file, and the MCP server serves approved and unconfirmed memories to your assistants">
</p>

1. **Ingest** reads local session files. Only the turns you wrote leave the parsing step.
2. **Extract** asks a model you already use, through your own signed-in `claude` or `codex` CLI,
   to propose memories. The CLI runs with its tools off, in an empty temporary directory.
3. **Store** keeps each memory with its source quote, a state, and a scope.
4. **Review** is optional. Memories you never review are served marked *unconfirmed*; you
   can approve, restrict, hide or forget any of them at any time.
5. **Serve** exposes the store to assistants over MCP, with the evidence attached.
6. **Tidy** (on request) folds near-identical memories from the same session into one, and
   archives unconfirmed memories not seen again for 90 days. It shows a plan first; nothing changes without `--apply`, nothing is deleted, and `personakit undo <id>`
   reverses a step.

A memory is always in one of four states:

| State | Served to assistants? |
|---|---|
| `unconfirmed` (default) | Yes, labelled as unconfirmed |
| `approved` | Yes |
| `restricted` | Never |
| `archived` | Never |

## Limits in 0.2

Stated plainly, so you know what you are installing:

- **Extraction is a model's guess.** Review is how you correct it.
- **Ranking is word overlap**, on whole words in Latin letters and digits. Questions and memories
  in other scripts are not matched yet; approved memories are still returned as standing context.
- **A decision cannot be changed, only undone by forgetting.** `review` shows unconfirmed memories;
  there is no command yet to edit a memory's wording or move a decided memory to another state.
- **Twin detection compares words, not meaning.** It folds memories phrased almost the same way,
  from the same session, and misses paraphrases on purpose: a missed merge costs nothing, a wrong
  one costs trust. Expect it to find little when the same fact is worded differently each time.
- **Decay looks only at time.** An unconfirmed memory not extracted again for 90 days is archived
  (reversible); that says nothing about whether it is still true. Approved and restricted
  memories never decay.
- **A memory an assistant already received stays in that conversation.** Restricting it applies to
  future reads.
- **Paste and credential detection is by shape**, not by meaning. Look before you share a store.

## What works today

| | Status |
|---|---|
| Claude Code sessions | Available in 0.1 |
| Codex sessions | Available in 0.1 |
| Any MCP client (read and propose) | Available in 0.1 |
| Merge of near-identical same-session memories (reversible) | Available in 0.2 |
| Decay of stale unconfirmed memories (reversible) | Available in 0.2 |
| Digest of the last days | Available in 0.2 |
| ChatGPT, claude.ai and Gemini export import | Planned for 0.3 |

## Documentation

- [personakit.me/docs](https://personakit.me/docs/): guides, concepts, and the MCP tools reference.
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
