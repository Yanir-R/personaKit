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

    def test_list_loads_the_same_evidence_as_get_in_one_pass(self):
        first, second = memory(turn=0), memory("You use Python.", "I write Python.", 1)
        for item in (first, second, memory(turn=5, quote="Be blunt.")):
            self.store.add(item)
        listed = self.store.list()
        self.assertEqual([m.evidence for m in listed], [self.store.get(m.id).evidence for m in listed])
        self.assertEqual(len(listed[0].evidence), 2)
        self.assertEqual([e.turn_index for e in listed[0].evidence], [0, 5])
        only_python = self.store.list(states=[State.UNCONFIRMED], scope="global")
        self.assertEqual(len(only_python), 2)

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

    def test_reads_are_counted_without_content(self):
        self.store.log_read(2, 1)
        self.store.log_read(0, 0)
        self.assertEqual(self.store.read_stats(), {"reads": 2, "reads_with_results": 1})

    def test_existing_database_is_upgraded_in_place(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "old.db"
        old = sqlite3.connect(path)
        old.executescript(MIGRATIONS[0])
        old.execute("PRAGMA user_version = 1")
        old.execute("INSERT INTO memories VALUES ('m_x','kept','c','global','approved','2026-01-01T00:00:00Z',NULL,NULL)")
        old.execute("INSERT INTO evidence VALUES ('m_x','s',0,'q')")
        old.commit()
        old.close()
        with Store(path) as upgraded:
            self.assertEqual(upgraded.get("m_x").text, "kept")
            self.assertEqual(upgraded.read_stats()["reads"], 0)
            version = upgraded._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, len(MIGRATIONS))

    def test_database_from_before_hints_opens_without_losing_anything(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "before-hints.db"
        old = sqlite3.connect(path)
        for number, script in enumerate(MIGRATIONS[:4]):
            old.executescript(script)
            old.execute(f"PRAGMA user_version = {number + 1}")
        old.execute("INSERT INTO memories (id, text, category, scope, state, created_at, decided_at, decided_by, last_seen_at)"
                    " VALUES ('m_old','You keep notes in plain text.','tools','global','approved','2026-01-01T00:00:00Z',"
                    "'2026-01-02T00:00:00Z','owner','2026-01-03T00:00:00Z')")
        old.execute("INSERT INTO evidence VALUES ('m_old','s',4,'Plain text forever.')")
        old.execute("INSERT INTO reads VALUES ('2026-01-04T00:00:00Z', 1, 0)")
        old.commit()
        old.close()
        with Store(path) as upgraded:
            loaded = upgraded.get("m_old")
            self.assertEqual((loaded.text, loaded.state, loaded.decided_by), ("You keep notes in plain text.", State.APPROVED, Decider.OWNER))
            self.assertEqual((loaded.last_seen_at, loaded.evidence), ("2026-01-03T00:00:00Z", (Evidence("s", 4, "Plain text forever."),)))
            self.assertEqual((loaded.answers, loaded.applies_when), ((), ()))
            self.assertEqual(upgraded.read_stats()["reads"], 1)
            upgraded.set_hints("m_old", answers=["Where do notes go?"])
            self.assertEqual(upgraded.get("m_old").answers, ("Where do notes go?",))
        with Store(path) as reopened:
            self.assertEqual(reopened.get("m_old").answers, ("Where do notes go?",))
            self.assertEqual(reopened._conn.execute("PRAGMA user_version").fetchone()[0], len(MIGRATIONS))

    def test_hints_round_trip_and_leave_the_decision_alone(self):
        m = Memory(text="You prefer tabs.", category="tools", evidence=(Evidence("s", 0, "Tabs."),),
                   answers=("Tabs or spaces?",))
        self.store.add(m)
        self.store.set_state(m.id, State.APPROVED, Decider.OWNER)
        self.assertEqual(self.store.get(m.id).answers, ("Tabs or spaces?",))
        updated = self.store.set_hints(m.id, applies_when=["  editing   Go code ", "", "editing Go code"])
        self.assertEqual((updated.answers, updated.applies_when), (("Tabs or spaces?",), ("editing Go code",)))
        self.assertEqual((updated.state, updated.decided_at), (State.APPROVED, "2026-01-07T00:00:00Z"))
        self.assertEqual(self.store.list()[0].applies_when, ("editing Go code",))
        cleared = self.store.set_hints(m.id, answers=[])
        self.assertEqual((cleared.answers, cleared.applies_when), ((), ("editing Go code",)))
        self.assertEqual(updated.as_dict()["applies_when"], ["editing Go code"])
        with self.assertRaises(KeyError):
            self.store.set_hints("m_missing", answers=["x"])

    def test_database_records_its_schema_version(self):
        version = self.store._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, len(MIGRATIONS))


if __name__ == "__main__":
    unittest.main()
