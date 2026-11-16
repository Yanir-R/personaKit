"""Extension points: swap how relevance and similarity are scored, nothing else.

A plugin is a Python package you installed that registers an entry point in the
`personakit.plugins` group. The entry point is a function that receives a `Hooks` object and
replaces the scoring functions it provides. Nothing is loaded unless you name it in the
PERSONAKIT_PLUGINS environment variable (comma separated), so installing a package never
changes how PersonaKit behaves by itself.

A plugin only scores. Which memories may be served, which may be merged, and every state change
stay in `retrieve`, `twins` and `store`. A plugin is still code running as you, with access to
your store file: enable only ones you trust.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from personakit import retrieve, twins

GROUP = "personakit.plugins"
ENABLE_ENV = "PERSONAKIT_PLUGINS"


class PluginError(Exception):
    """A plugin that was asked for could not be used."""


@dataclass
class Hooks:
    """The functions a plugin may replace. The defaults are the built-in word-based ones."""

    relevance: retrieve.Relevance = retrieve.overlap  # (question, memories) -> one score per memory
    similarity: twins.Similarity = twins.similarity  # (text, text) -> 0 to 1


def enabled_names() -> list[str]:
    return [name.strip() for name in os.environ.get(ENABLE_ENV, "").split(",") if name.strip()]


def load(
    names: Iterable[str] | None = None,
    discover: Callable[[], Iterable[EntryPoint]] = lambda: entry_points(group=GROUP),
) -> Hooks:
    """Hooks with every named plugin applied, in the order named. No names, no plugins."""
    hooks = Hooks()
    wanted = enabled_names() if names is None else list(names)
    if not wanted:
        return hooks
    installed = {point.name: point for point in discover()}
    for name in wanted:
        if name not in installed:
            raise PluginError(f"plugin {name!r} is named in {ENABLE_ENV} but is not installed")
        installed[name].load()(hooks)
    if not callable(hooks.relevance) or not callable(hooks.similarity):
        raise PluginError("a plugin replaced a hook with something that cannot be called")
    return hooks
