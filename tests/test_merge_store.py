import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from personakit.model import Decider, Evidence, Memory, State
from personakit.store import MIGRATIONS, Store


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

    def test_merge_moves_evidence_and_removes_the_duplicate(self):
        self.merged()
        self.assertIsNone(self.store.get(self.dup.id))
        self.assertEqual([(e.turn_index, e.quote) for e in self.store.get(self.keep.id).evidence], [(0, "Skip the pep talk."), (1, "Be blunt.")])
        self.assertEqual([r.duplicate_id for r in self.store.merges()], [self.dup.id])

    def test_undo_restores_the_duplicate_and_takes_back_only_what_it_added(self):
        self.merged()
        self.store.undo_merge(self.dup.id)
        restored = self.store.get(self.dup.id)
        self.assertEqual((restored.text, restored.state), (self.dup.text, State.UNCONFIRMED))
        self.assertEqual(len(restored.evidence), 2)
        # the quote both memories shared stays with the survivor
        self.assertEqual([e.turn_index for e in self.store.get(self.keep.id).evidence], [0])
        self.assertEqual(self.store.merges(), [])

    def test_undo_drops_the_stored_text_but_remembers_the_pair(self):
        self.merged()
        self.store.undo_merge(self.dup.id)
        (record,) = self.store.merges(active_only=False)
        self.assertEqual((record.duplicate_text, bool(record.undone_at)), ("", True))
        with self.assertRaises(KeyError):
            self.store.undo_merge(self.dup.id)

    def test_only_unconfirmed_memories_can_merge(self):
        self.store.set_state(self.keep.id, State.APPROVED, Decider.OWNER)
        with self.assertRaises(ValueError):
            self.merged()
        with self.assertRaises(ValueError):
            self.store.merge(self.dup.id, self.dup.id)
        with self.assertRaises(KeyError):
            self.store.merge("m_missing", self.keep.id)

    def test_extracting_a_merged_statement_again_feeds_the_survivor(self):
        self.merged()
        self.clock.value = "2026-02-01T00:00:00Z"
        self.assertFalse(self.store.add(mem(self.dup.text, (5, "Straight talk please."))))
        self.assertIsNone(self.store.get(self.dup.id))
        survivor = self.store.get(self.keep.id)
        self.assertEqual(len(survivor.evidence), 3)
        self.assertEqual(survivor.last_seen_at, "2026-02-01T00:00:00Z")

    def test_forgetting_the_survivor_deletes_what_the_merge_kept(self):
        self.merged()
        self.assertTrue(self.store.forget(self.keep.id))
        self.assertEqual(self.store.merges(active_only=False), [])
        self.assertNotIn(self.dup.text, json.dumps(self.store._conn.execute("SELECT * FROM merges").fetchall()))

    def test_forgetting_removes_chained_merges_as_well(self):
        third = mem("You prefer direct, practical feedback always.", (7, "Always."))
        self.store.add(third)
        self.merged()
        self.store.merge(self.keep.id, third.id)  # the survivor is itself folded into a third memory
        self.assertTrue(self.store.forget(third.id))
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM merges").fetchone()[0], 0)

    def test_forgetting_a_merged_duplicate_removes_it_and_the_evidence_it_gave(self):
        self.merged()
        self.assertTrue(self.store.forget(self.dup.id))
        self.assertEqual([e.turn_index for e in self.store.get(self.keep.id).evidence], [0])
        self.assertEqual(self.store.merges(active_only=False), [])
        self.assertFalse(self.store.forget(self.dup.id))

    def test_forgetting_after_undo_clears_the_pair_record_too(self):
        self.merged()
        self.store.undo_merge(self.dup.id)
        self.assertTrue(self.store.forget(self.dup.id))
        self.assertEqual(self.store.merges(active_only=False), [])

    def test_merges_can_be_filtered_by_time(self):
        self.clock.value = "2026-03-01T00:00:00Z"
        self.merged()
        self.assertEqual(len(self.store.merges(since="2026-02-01T00:00:00Z")), 1)
        self.assertEqual(self.store.merges(since="2026-04-01T00:00:00Z"), [])


class DecayStoreTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = Store(":memory:", now=self.clock)
        self.addCleanup(self.store.close)
        self.m = mem("You use Python for scripts.", (0, "I write Python."))
        self.store.add(self.m)

    def test_new_memory_is_last_seen_when_created(self):
        self.assertEqual(self.store.get(self.m.id).last_seen_at, "2026-01-01T00:00:00Z")

    def test_seeing_it_again_refreshes_last_seen(self):
        self.clock.value = "2026-04-01T00:00:00Z"
        self.store.add(mem(self.m.text, (3, "More Python.")))
        self.assertEqual(self.store.get(self.m.id).last_seen_at, "2026-04-01T00:00:00Z")

    def test_restore_brings_back_a_policy_archive_and_resets_the_clock(self):
        self.store.set_state(self.m.id, State.ARCHIVED, Decider.POLICY)
        self.clock.value = "2026-05-01T00:00:00Z"
        self.store.restore(self.m.id)
        back = self.store.get(self.m.id)
        self.assertEqual((back.state, back.decided_by, back.last_seen_at), (State.UNCONFIRMED, None, "2026-05-01T00:00:00Z"))

    def test_restore_refuses_what_the_owner_archived(self):
        self.store.set_state(self.m.id, State.ARCHIVED, Decider.OWNER)
        with self.assertRaises(KeyError):
            self.store.restore(self.m.id)
        with self.assertRaises(KeyError):
            self.store.restore("m_missing")

    def test_extracting_an_archived_statement_again_revives_it_only_if_policy_archived_it(self):
        self.store.set_state(self.m.id, State.ARCHIVED, Decider.POLICY)
        self.store.add(mem(self.m.text, (4, "Python again.")))
        self.assertEqual(self.store.get(self.m.id).state, State.UNCONFIRMED)
        self.store.set_state(self.m.id, State.ARCHIVED, Decider.OWNER)
        self.store.add(mem(self.m.text, (5, "Python once more.")))
        self.assertEqual(self.store.get(self.m.id).state, State.ARCHIVED)

    def test_database_from_before_merges_is_upgraded_and_backfilled(self):
        path = Path(tempfile.mkdtemp()) / "v2.db"
        old = sqlite3.connect(path)
        for step in MIGRATIONS[:2]:
            old.executescript(step)
        old.execute("PRAGMA user_version = 2")
        old.execute("INSERT INTO memories VALUES ('m_x','kept','c','global','unconfirmed','2026-01-01T00:00:00Z',NULL,NULL)")
        old.execute("INSERT INTO evidence VALUES ('m_x','s',0,'q')")
        old.commit()
        old.close()
        with Store(path) as upgraded:
            self.assertEqual(upgraded.get("m_x").last_seen_at, "2026-01-01T00:00:00Z")
            self.assertEqual(upgraded.merges(), [])


if __name__ == "__main__":
    unittest.main()
