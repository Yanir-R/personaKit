import unittest

from personakit.model import Decider, Evidence, Memory, State
from personakit.store import Store


class Clock:
    def __init__(self, value="2026-01-01T00:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value


def mem(text, *evidence):
    return Memory(text=text, category="other", evidence=tuple(Evidence("s1", t, q) for t, q in evidence))


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = Store(":memory:", now=self.clock)
        self.addCleanup(self.store.close)
        self.keep = mem("You prefer direct practical feedback.", (0, "Skip the pep talk."))
        self.dup = mem("You prefer direct and practical feedback.", (1, "Be blunt."), (0, "Skip the pep talk."))
        self.store.add(self.keep)
        self.store.add(self.dup)

    def merged(self):
        self.store.merge(self.dup.id, self.keep.id)

    def quotes(self, memory_id):
        return [e.quote for e in self.store.get(memory_id).evidence]

    def test_merge_hides_the_duplicate_and_shows_its_evidence_on_the_survivor(self):
        self.merged()
        self.assertIsNone(self.store.get(self.dup.id))
        self.assertEqual([m.id for m in self.store.list()], [self.keep.id])
        self.assertEqual(self.quotes(self.keep.id), ["Skip the pep talk.", "Be blunt."])
        self.assertEqual(self.store.list()[0].evidence, self.store.get(self.keep.id).evidence)
        self.assertEqual(self.store.counts()["unconfirmed"], 1)
        self.assertEqual([(r.duplicate_id, r.duplicate_text) for r in self.store.merges()], [(self.dup.id, self.dup.text)])

    def test_undo_is_exact(self):
        before = (self.store.get(self.keep.id), self.store.get(self.dup.id))
        self.clock.value = "2026-02-01T00:00:00Z"
        self.store.add(mem(self.dup.text, (1, "Be blunt.")))  # the duplicate was seen more recently
        fresh_dup = self.store.get(self.dup.id)
        self.merged()
        self.assertEqual(self.store.get(self.keep.id).last_seen_at, "2026-02-01T00:00:00Z")
        self.store.undo_merge(self.dup.id)
        self.assertEqual((self.store.get(self.keep.id), self.store.get(self.dup.id)), (before[0], fresh_dup))
        self.assertEqual(self.store.merges(), [])
        with self.assertRaises(KeyError):
            self.store.undo_merge(self.dup.id)

    def test_an_undone_pair_stays_vetoed_even_after_other_merges(self):
        other = mem("You prefer direct, practical feedback always.", (7, "Always."))
        self.store.add(other)
        self.merged()
        self.store.undo_merge(self.dup.id)
        self.store.merge(self.dup.id, other.id)
        self.store.undo_merge(self.dup.id)
        self.assertEqual(
            self.store.merge_vetoes(),
            {frozenset((self.dup.id, self.keep.id)), frozenset((self.dup.id, other.id))},
        )

    def test_only_unconfirmed_standalone_memories_can_merge(self):
        with self.assertRaises(ValueError):
            self.store.merge(self.dup.id, self.dup.id)
        with self.assertRaises(KeyError):
            self.store.merge("m_missing", self.keep.id)
        self.store.set_state(self.keep.id, State.APPROVED, Decider.OWNER)
        with self.assertRaises(ValueError):
            self.merged()

    def test_a_merged_memory_cannot_change_state_on_its_own(self):
        self.merged()
        with self.assertRaises(KeyError):
            self.store.set_state(self.dup.id, State.APPROVED, Decider.OWNER)

    def test_extracting_a_merged_statement_again_feeds_the_survivor(self):
        self.merged()
        self.clock.value = "2026-02-01T00:00:00Z"
        self.assertFalse(self.store.add(mem(self.dup.text, (5, "Straight talk please."))))
        self.assertIsNone(self.store.get(self.dup.id))
        survivor = self.store.get(self.keep.id)
        self.assertEqual(len(survivor.evidence), 3)
        self.assertEqual(survivor.last_seen_at, "2026-02-01T00:00:00Z")
        self.assertEqual(self.store.list()[0].last_seen_at, "2026-02-01T00:00:00Z")

    def chain(self):
        """dup folded into keep, then keep folded into a third memory."""
        self.third = mem("You prefer direct, practical feedback always.", (7, "Always."))
        self.store.add(self.third)
        self.merged()
        self.store.merge(self.keep.id, self.third.id)

    def test_chained_merges_show_all_evidence_on_the_last_survivor(self):
        self.chain()
        self.assertEqual(self.quotes(self.third.id), ["Skip the pep talk.", "Be blunt.", "Always."])
        self.assertEqual(self.store.list()[0].evidence, self.store.get(self.third.id).evidence)

    def test_extracting_again_after_a_chained_merge_works_and_lands_on_the_last_survivor(self):
        self.chain()
        self.assertFalse(self.store.add(mem(self.dup.text, (9, "Blunt again."))))
        self.assertIn("Blunt again.", self.quotes(self.third.id))

    def test_forgetting_a_merged_memory_removes_every_quote_it_brought_even_through_a_chain(self):
        self.chain()
        self.store.add(mem(self.dup.text, (9, "Blunt again.")))  # arrived after the merge
        self.assertTrue(self.store.forget(self.dup.id))
        self.assertEqual(self.quotes(self.third.id), ["Skip the pep talk.", "Always."])
        self.store.undo_merge(self.keep.id)
        self.assertEqual(self.quotes(self.keep.id), ["Skip the pep talk."])
        everything = repr([tuple(r) for r in self.store._conn.execute("SELECT * FROM evidence")])
        self.assertNotIn("Be blunt.", everything)
        self.assertNotIn("Blunt again.", everything)
        self.assertFalse(self.store.forget(self.dup.id))

    def test_forgetting_the_survivor_forgets_everything_folded_into_it(self):
        self.chain()
        self.assertTrue(self.store.forget(self.third.id))
        for table in ("memories", "evidence", "merge_vetoes"):
            self.assertEqual(self.store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

    def test_forgetting_clears_vetoes_that_mention_the_memory(self):
        self.merged()
        self.store.undo_merge(self.dup.id)
        self.store.forget(self.dup.id)
        self.assertEqual(self.store.merge_vetoes(), frozenset())

    def test_merges_can_be_filtered_by_time(self):
        self.clock.value = "2026-03-01T00:00:00Z"
        self.merged()
        self.assertEqual(len(self.store.merges(since="2026-02-01T00:00:00Z")), 1)
        self.assertEqual(self.store.merges(since="2026-04-01T00:00:00Z"), [])


if __name__ == "__main__":
    unittest.main()
