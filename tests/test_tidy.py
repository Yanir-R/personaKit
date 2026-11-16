import unittest

from personakit import tidy
from personakit.model import Decider, Evidence, Memory, State
from personakit.store import Store

NOW = "2026-06-01T00:00:00Z"


def mem(text, session="s1", turn=0):
    return Memory(text=text, category="other", evidence=(Evidence(session, turn, f"quote {turn}"),))


class TidyTest(unittest.TestCase):
    def setUp(self):
        self.clock = ["2026-01-01T00:00:00Z"]
        self.store = Store(":memory:", now=lambda: self.clock[0])
        self.addCleanup(self.store.close)
        self.old = mem("You deploy on Fridays.")
        self.approved = mem("You prefer direct, practical feedback.", turn=1)
        for memory in (self.old, self.approved):
            self.store.add(memory)
        self.store.set_state(self.approved.id, State.APPROVED, Decider.OWNER)
        self.clock[0] = NOW
        self.fresh = mem("You use Python for scripts.", session="s2")
        self.store.add(self.fresh)

    def test_plan_lists_only_stale_unconfirmed_memories_and_changes_nothing(self):
        plan = tidy.make_plan(self.store, NOW, days=90)
        self.assertEqual([m.id for m in plan.stale], [self.old.id])
        self.assertEqual(self.store.counts()["archived"], 0)

    def test_apply_archives_by_policy_and_undo_brings_it_back(self):
        tidy.apply(self.store, tidy.make_plan(self.store, NOW, days=90))
        archived = self.store.get(self.old.id)
        self.assertEqual((archived.state, archived.decided_by), (State.ARCHIVED, Decider.POLICY))
        self.assertEqual(self.store.get(self.approved.id).state, State.APPROVED)
        tidy.undo(self.store, self.old.id)
        self.assertEqual(self.store.get(self.old.id).state, State.UNCONFIRMED)

    def test_a_restored_memory_is_not_archived_again_straight_away(self):
        tidy.apply(self.store, tidy.make_plan(self.store, NOW, days=90))
        tidy.undo(self.store, self.old.id)
        self.assertEqual(tidy.make_plan(self.store, NOW, days=90).stale, [])

    def test_applying_twice_is_a_no_op(self):
        tidy.apply(self.store, tidy.make_plan(self.store, NOW, days=90))
        self.assertEqual(tidy.make_plan(self.store, NOW, days=90).stale, [])

    def test_undo_refuses_unknown_ids_and_owner_archives(self):
        self.store.set_state(self.fresh.id, State.ARCHIVED, Decider.OWNER)
        for memory_id in ("m_missing", self.fresh.id, self.approved.id):
            with self.assertRaises(KeyError):
                tidy.undo(self.store, memory_id)


if __name__ == "__main__":
    unittest.main()
