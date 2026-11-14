import unittest
from unittest import mock

from personakit import mcp_server, plugins, retrieve
from personakit.model import Decider, Evidence, Memory, State
from personakit.store import Store


class FakePoint:
    """Stands in for an installed entry point."""

    def __init__(self, name, register):
        self.name, self._register = name, register

    def load(self):
        return self._register


def everything_matches(question, memories):
    return [1.0] * len(memories)


def use_everything_matches(hooks):
    hooks.relevance = everything_matches


INSTALLED = [FakePoint("match-all", use_everything_matches), FakePoint("other", lambda hooks: None)]


def mem(text, session="s1", turn=0, state=State.UNCONFIRMED):
    return Memory(
        text=text,
        category="other",
        state=state,
        decided_by=Decider.OWNER if state != State.UNCONFIRMED else None,
        evidence=(Evidence(session, turn, "invented"),),
    )


class LoadTest(unittest.TestCase):
    def load(self, names):
        return plugins.load(names, discover=lambda: INSTALLED)

    def test_nothing_is_loaded_unless_named(self):
        self.assertIs(self.load([]).relevance, retrieve.overlap)

    def test_installed_but_unnamed_plugins_stay_off(self):
        self.assertIs(self.load(["other"]).relevance, retrieve.overlap)

    def test_named_plugins_replace_what_they_provide(self):
        self.assertIs(self.load(["match-all", "other"]).relevance, everything_matches)

    def test_naming_a_missing_plugin_is_an_error_not_a_silent_fallback(self):
        with self.assertRaises(plugins.PluginError):
            self.load(["not-installed"])

    def test_a_plugin_that_breaks_a_hook_is_refused(self):
        broken = [FakePoint("broken", lambda hooks: setattr(hooks, "relevance", None))]
        with self.assertRaises(plugins.PluginError):
            plugins.load(["broken"], discover=lambda: broken)

    def test_names_come_from_the_environment(self):
        with mock.patch.dict("os.environ", {plugins.ENABLE_ENV: " match-all , ,other "}):
            self.assertEqual(plugins.enabled_names(), ["match-all", "other"])
        with mock.patch.dict("os.environ", {plugins.ENABLE_ENV: ""}):
            self.assertIs(plugins.load().relevance, retrieve.overlap)


class PolicyStaysInCoreTest(unittest.TestCase):
    """A plugin scores; it cannot widen what is served."""

    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def test_relevance_plugin_cannot_serve_restricted_or_archived_memories(self):
        for text, state in (
            ("You like tea in the morning.", State.APPROVED),
            ("You keep a private diary.", State.RESTRICTED),
            ("You once used an old editor.", State.ARCHIVED),
        ):
            memory = mem(text)
            self.store.add(memory)
            if state != State.UNCONFIRMED:
                self.store.set_state(memory.id, state, Decider.OWNER)
        result = mcp_server.read_memories(self.store, "unrelated question", relevance=everything_matches)
        self.assertEqual([m["text"] for m in result["memories"]], ["You like tea in the morning."])
        self.assertEqual(result["withheld"], 1)


if __name__ == "__main__":
    unittest.main()
