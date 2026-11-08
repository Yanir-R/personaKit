# Contributing

Thanks for helping. PersonaKit is pre-release; the design is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the plan in [docs/ROADMAP.md](docs/ROADMAP.md).

## Ground rules

- **Privacy first.** Never commit real conversations, memories, paths, hostnames or credentials.
  Test fixtures use invented data only. `scripts/check_hygiene.sh` runs in CI and catches the
  obvious cases, but it is not a substitute for reading your own diff.
- **Respect the module boundaries.** Only `store` touches SQLite, only `llm` talks to a model, only
  `ingest` reads session files. If you need to break a boundary, open an issue first.
- **No duplicated logic.** Reuse an existing helper or move it to the right module.
- **Small pull requests.** One change, with tests and a doc update if behavior or a privacy claim changes.

## Workflow

1. Open an issue for anything beyond a small fix, so the approach can be agreed.
2. Fork, branch from `main`, and make the change.
3. Fill in the pull request template.
4. A maintainer reviews. Every file is read for personal data and duplication before it merges.

## License

By contributing you agree that your contribution is licensed under the Apache License 2.0, as in
[LICENSE](LICENSE). No separate CLA is required.

## Conduct

Be respectful and assume good faith. Harassment and personal attacks are not tolerated;
maintainers may remove content and block contributors who engage in them.
