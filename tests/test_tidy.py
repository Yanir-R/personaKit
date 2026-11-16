import unittest

from personakit import tidy
from personakit.model import Decider, Evidence, Memory, State
from personakit.store import Store

NOW = "2026-06-01T00:00:00Z"


def mem(text, session="s1", turn=0, category="communication"):
    return Memory(text=text, category=category, evidence=(Evidence(session, turn, f"quote {turn}"),))


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class TidyTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock("2026-01-01T00:00:00Z")
        self.store = Store(":memory:", now=self.clock)
        self.addCleanup(self.store.close)
        self.keep = mem("You prefer direct, practical feedback.")
        self.twin = mem("You prefer direct and practical feedback from reviewers.", turn=1)
        self.old = mem("You deploy on Fridays.", session="s2", category="work")
        for m in (self.keep, self.twin, self.old):
            self.store.add(m)
            self.clock.value = self.tick(self.clock.value)
        self.clock.value = NOW
        self.fresh = mem("You use Python for scripts.", session="s3", category="tools")
        self.store.add(self.fresh)

    @staticmethod
    def tick(value):
        return value[:-3] + f"{int(value[-3:-1]) + 1:02d}Z"

    def test_plan_changes_nothing(self):
        plan = tidy.make_plan(self.store, NOW, days=90)
        self.assertEqual((plan.merges, len(plan.stale)), (1, 2))
        self.assertEqual(self.store.counts()["unconfirmed"], 4)
        self.assertEqual(self.store.merges(), [])

    def test_stale_list_leaves_out_memories_about_to_be_folded_away(self):
        plan = tidy.make_plan(self.store, NOW, days=90)
        self.assertEqual({m.id for m in plan.stale}, {self.keep.id, self.old.id})

    def test_apply_merges_and_archives_and_every_step_can_be_undone(self):
        report = tidy.apply(self.store, tidy.make_plan(self.store, NOW, days=90))
        self.assertEqual((report.merged, report.archived), (1, 2))
        self.assertEqual(self.store.get(self.old.id).state, State.ARCHIVED)
        self.assertEqual(self.store.get(self.old.id).decided_by, Decider.POLICY)
        self.assertEqual(tidy.undo(self.store, self.twin.id), "unmerged")
        self.assertEqual(tidy.undo(self.store, self.old.id), "restored")
        self.assertEqual(tidy.undo(self.store, self.keep.id), "restored")
        self.assertEqual(self.store.counts(), {"unconfirmed": 4, "approved": 0, "restricted": 0, "archived": 0})

    def test_a_merge_the_owner_undid_is_not_proposed_again(self):
        tidy.apply(self.store, tidy.make_plan(self.store, NOW, days=90, archive=False))
        tidy.undo(self.store, self.twin.id)
        self.assertEqual(tidy.make_plan(self.store, NOW, days=90, archive=False).groups, [])

    def test_a_survivor_is_not_stale_when_its_twin_was_seen_recently(self):
        self.store.add(mem(self.twin.text, turn=1))  # the twin is extracted again today
        plan = tidy.make_plan(self.store, NOW, days=90)
        self.assertEqual((plan.merges, [m.id for m in plan.stale]), (1, [self.old.id]))
        tidy.apply(self.store, plan)
        self.assertEqual(self.store.get(self.keep.id).state, State.UNCONFIRMED)
        self.assertEqual(tidy.make_plan(self.store, NOW, days=90).stale, [])

    def test_steps_can_run_alone(self):
        self.assertEqual(tidy.make_plan(self.store, NOW, merge=False).groups, [])
        self.assertEqual(tidy.make_plan(self.store, NOW, archive=False).stale, [])

    def test_undo_refuses_unknown_ids_and_owner_archives(self):
        self.store.set_state(self.fresh.id, State.ARCHIVED, Decider.OWNER)
        for memory_id in ("m_missing", self.fresh.id):
            with self.assertRaises(KeyError):
                tidy.undo(self.store, memory_id)

    def test_applying_twice_is_a_no_op(self):
        tidy.apply(self.store, tidy.make_plan(self.store, NOW, days=90))
        again = tidy.apply(self.store, tidy.make_plan(self.store, NOW, days=90))
        self.assertEqual((again.merged, again.archived), (0, 0))


if __name__ == "__main__":
    unittest.main()
