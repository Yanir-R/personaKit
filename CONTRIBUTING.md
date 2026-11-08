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
3. Sign off every commit (see below).
4. Fill in the pull request template.
5. A maintainer reviews. Every file is read for personal data and duplication before it merges.

## Sign your commits (DCO)

This project uses the [Developer Certificate of Origin](DCO) instead of a CLA. By signing off you
certify that you wrote the contribution or have the right to submit it under Apache-2.0.

```sh
git commit -s -m "Describe the change"
```

This adds a `Signed-off-by: Your Name <you@example.com>` line, which must match your git
`user.name` and `user.email`. To fix existing commits: `git rebase --signoff main`.
A CI check blocks pull requests that contain unsigned commits.

Contributions stay under the license of the file they change (Apache-2.0). You keep your own
copyright; the project does not ask for copyright assignment.

## License and name

Code is licensed under the Apache License 2.0, as in [LICENSE](LICENSE). The project name and
branding are covered by [TRADEMARK.md](TRADEMARK.md).

## Conduct

Be respectful and assume good faith. Harassment and personal attacks are not tolerated;
maintainers may remove content and block contributors who engage in them.
