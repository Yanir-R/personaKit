# Plugins

PersonaKit has two extension points. Both replace a scoring function and nothing else.

| Hook | Signature | Built-in | Used by |
|---|---|---|---|
| `relevance` | `(question: str, memories: Sequence[Memory]) -> Sequence[float]` | word overlap | `personakit serve` (which memories answer a question, and in what order) |
| `similarity` | `(a: str, b: str) -> float` between 0 and 1 | shared words, with number, negation and order guards | `personakit tidy` (which same-session memories are twins) |

## What a plugin cannot do

Policy stays in the core, whatever a plugin returns:

- Restricted and archived memories are never served. A relevance score only orders what the read
  policy already allows.
- Only unconfirmed memories from the same single session, with the same category and scope, can
  be proposed as twins. Merging still needs `personakit tidy --apply` and is reversible.
- No hook can approve, restrict, archive, restore or forget.

A plugin is still Python code running as you, with access to your store file. Enable only
plugins you trust and have read.

## Enabling one

Nothing is loaded just because it is installed. Name the plugins you want:

```sh
pip install some-personakit-plugin
export PERSONAKIT_PLUGINS=some-name        # comma separated for several, applied in order
personakit tidy
```

A name that is not installed is an error, not a silent fallback.

## Writing one

Register a function in the `personakit.plugins` entry-point group. It receives a `Hooks` object
and replaces what it provides:

```toml
# pyproject.toml of the plugin
[project.entry-points."personakit.plugins"]
some-name = "some_package:register"
```

```python
# some_package/__init__.py
def register(hooks):
    hooks.similarity = my_similarity      # leave hooks.relevance alone to keep the built-in
```

For anything beyond scoring, use PersonaKit as a library: `personakit.store.Store` is the one
place that reads and writes the database, and `Store.merge`, `Store.undo_merge`,
`Store.set_state` and `Store.restore` are the same reversible operations the CLI uses.
