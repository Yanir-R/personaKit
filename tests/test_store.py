import unittest

from personakit.model import Decider, Evidence, Memory, State, memory_id
from personakit.store import MIGRATIONS, Store


def memory(text="You prefer direct, practical feedback.", quote="Skip the pep talk.", turn=0):
    return Memory(
        text=text,
        category="communication",
        evidence=(Evidence("s1", turn, quote),),
    )


class ModelTest(unittest.TestCase):
    def test_memory_without_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            Memory(text="x", category="c", evidence=())

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            Memory(text="  ", category="c", evidence=(Evidence("s", 0, "q"),))

    def test_id_ignores_case_and_whitespace(self):
        self.assertEqual(memory_id("You  prefer X"), memory_id("you prefer x "))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:", now=lambda: "2026-01-07T00:00:00Z")
        self.addCleanup(self.store.close)

    def test_round_trip(self):
        m = memory()
        self.assertTrue(self.store.add(m))
        loaded = self.store.get(m.id)
        self.assertEqual(loaded.text, m.text)
        self.assertEqual(loaded.state, State.UNCONFIRMED)
        self.assertEqual(loaded.created_at, "2026-01-07T00:00:00Z")
        self.assertEqual(loaded.evidence, m.evidence)

    def test_adding_the_same_memory_merges_evidence_and_keeps_the_decision(self):
        m = memory()
        self.store.add(m)
        self.store.set_state(m.id, State.APPROVED, Decider.OWNER)
        self.assertFalse(self.store.add(memory(text="you prefer direct, practical feedback.", quote="Again.", turn=3)))
        loaded = self.store.get(m.id)
        self.assertEqual(loaded.state, State.APPROVED)
        self.assertEqual(len(loaded.evidence), 2)

    def test_set_state_records_who_and_when(self):
        m = memory()
        self.store.add(m)
        self.store.set_state(m.id, State.ARCHIVED, Decider.POLICY)
        loaded = self.store.get(m.id)
        self.assertEqual((loaded.state, loaded.decided_by), (State.ARCHIVED, Decider.POLICY))
        self.assertEqual(loaded.decided_at, "2026-01-07T00:00:00Z")

    def test_set_state_on_unknown_memory_raises(self):
        with self.assertRaises(KeyError):
            self.store.set_state("m_missing", State.APPROVED, Decider.OWNER)

    def test_archived_memory_can_be_restored(self):
        m = memory()
        self.store.add(m)
        self.store.set_state(m.id, State.ARCHIVED, Decider.POLICY)
        self.store.set_state(m.id, State.UNCONFIRMED, Decider.OWNER)
        self.assertEqual(self.store.get(m.id).state, State.UNCONFIRMED)

    def test_forget_removes_memory_and_evidence(self):
        m = memory()
        self.store.add(m)
        self.assertTrue(self.store.forget(m.id))
        self.assertIsNone(self.store.get(m.id))
        left = self.store._conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        self.assertEqual(left, 0)
        self.assertFalse(self.store.forget(m.id))

    def test_list_filters_by_state_and_scope(self):
        a, b = memory(), memory(text="You like short answers.")
        self.store.add(a)
        self.store.add(b)
        self.store.set_state(b.id, State.APPROVED, Decider.OWNER)
        self.assertEqual([m.id for m in self.store.list(states=[State.APPROVED])], [b.id])
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(self.store.list(scope="work"), [])

    def test_counts_cover_every_state(self):
        self.store.add(memory())
        self.assertEqual(
            self.store.counts(),
            {"unconfirmed": 1, "approved": 0, "restricted": 0, "archived": 0},
        )

    def test_session_fingerprint_detects_change(self):
        self.assertFalse(self.store.session_is_current("claude-code", "s1", "abc"))
        self.store.mark_session_seen("claude-code", "s1", "abc")
        self.assertTrue(self.store.session_is_current("claude-code", "s1", "abc"))
        self.assertFalse(self.store.session_is_current("claude-code", "s1", "def"))

    def test_database_records_its_schema_version(self):
        version = self.store._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, len(MIGRATIONS))


if __name__ == "__main__":
    unittest.main()
