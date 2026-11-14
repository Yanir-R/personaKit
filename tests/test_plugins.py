import unittest
from unittest import mock

from personakit import mcp_server, plugins, retrieve, tidy, twins
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


def use_always_twins(hooks):
    hooks.similarity = lambda a, b: 1.0


INSTALLED = [FakePoint("match-all", use_everything_matches), FakePoint("twin-all", use_always_twins)]


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
        hooks = self.load([])
        self.assertIs(hooks.relevance, retrieve.overlap)
        self.assertIs(hooks.similarity, twins.similarity)

    def test_installed_but_unnamed_plugins_stay_off(self):
        self.assertIs(self.load(["twin-all"]).relevance, retrieve.overlap)

    def test_named_plugins_replace_only_what_they_provide(self):
        hooks = self.load(["match-all", "twin-all"])
        self.assertIs(hooks.relevance, everything_matches)
        self.assertEqual(hooks.similarity("a", "b"), 1.0)

    def test_naming_a_missing_plugin_is_an_error_not_a_silent_fallback(self):
        with self.assertRaises(plugins.PluginError):
            self.load(["not-installed"])

    def test_a_plugin_that_breaks_a_hook_is_refused(self):
        broken = [FakePoint("broken", lambda hooks: setattr(hooks, "relevance", None))]
        with self.assertRaises(plugins.PluginError):
            plugins.load(["broken"], discover=lambda: broken)

    def test_names_come_from_the_environment(self):
        with mock.patch.dict("os.environ", {plugins.ENABLE_ENV: " match-all , ,twin-all "}):
            self.assertEqual(plugins.enabled_names(), ["match-all", "twin-all"])
        with mock.patch.dict("os.environ", {plugins.ENABLE_ENV: ""}):
            self.assertIs(plugins.load().relevance, retrieve.overlap)


class PolicyStaysInCoreTest(unittest.TestCase):
    """A plugin scores; it cannot widen what is served or what may be merged."""

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

    def test_similarity_plugin_cannot_merge_across_sessions_or_touch_decisions(self):
        same_a, same_b = mem("First statement here."), mem("Completely different words.", turn=1)
        other_session = mem("Another session entirely.", session="s2")
        approved = mem("An approved statement.", turn=2)
        for memory in (same_a, same_b, other_session, approved):
            self.store.add(memory)
        self.store.set_state(approved.id, State.APPROVED, Decider.OWNER)
        plan = tidy.make_plan(self.store, self.store.now(), archive=False, similarity=lambda a, b: 1.0)
        folded = {d.id for g in plan.groups for d in g.duplicates} | {g.survivor.id for g in plan.groups}
        self.assertEqual(folded, {same_a.id, same_b.id})


if __name__ == "__main__":
    unittest.main()
