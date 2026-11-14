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

    def test_an_unobserved_add_neither_revives_nor_refreshes(self):
        self.store.set_state(self.m.id, State.ARCHIVED, Decider.POLICY)
        self.clock.value = "2026-09-01T00:00:00Z"
        self.assertFalse(self.store.add(mem(self.m.text, (4, "Said by an assistant.")), observed=False))
        kept = self.store.get(self.m.id)
        self.assertEqual((kept.state, kept.last_seen_at), (State.ARCHIVED, "2026-01-01T00:00:00Z"))

    def test_database_from_before_decay_is_upgraded_and_backfilled(self):
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


if __name__ == "__main__":
    unittest.main()
