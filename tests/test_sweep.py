import os
import shutil
import tempfile
import unittest
from pathlib import Path

from personakit import llm, sweep
from personakit.ingest import claude_code
from personakit.model import Evidence, Memory, State
from personakit.store import Store
from tests.helpers import FakeClient, reply

FIXTURE = Path(__file__).parent / "fixtures" / "claude_code" / "session.jsonl"
MEMORY = {"text": "You prefer direct, practical feedback.", "category": "communication", "turns": [0, 2]}


class SweepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        project = self.tmp / "proj"
        project.mkdir()
        self.session_file = project / "one.jsonl"
        shutil.copy(FIXTURE, self.session_file)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def run_sweep(self, client, **kwargs):
        return sweep.sweep(self.store, claude_code, client, root=self.tmp, **kwargs)

    def test_extracts_and_stores_unconfirmed_memories(self):
        report = self.run_sweep(FakeClient(reply(MEMORY)))
        self.assertEqual((report.sessions_extracted, report.memories_new), (1, 1))
        (memory,) = self.store.list()
        self.assertEqual(memory.state, State.UNCONFIRMED)
        self.assertEqual(memory.evidence[0].quote, "Skip the pep talk. Give me the practical next step.")

    def test_unchanged_session_is_not_extracted_again(self):
        client = FakeClient(reply(MEMORY))
        self.run_sweep(client)
        report = self.run_sweep(client)
        self.assertEqual((report.sessions_unchanged, report.sessions_extracted), (1, 0))
        self.assertEqual(len(client.prompts), 1)

    def test_changed_session_is_extracted_again_and_merges(self):
        client = FakeClient(reply(MEMORY))
        self.run_sweep(client)
        with open(self.session_file, "a") as handle:
            handle.write("\n")
        os.utime(self.session_file, ns=(1, 1))
        report = self.run_sweep(client)
        self.assertEqual((report.sessions_extracted, report.memories_new, report.memories_merged), (1, 0, 1))

    def test_only_owner_turns_are_sent_to_the_model(self):
        client = FakeClient(reply(MEMORY))
        self.run_sweep(client)
        prompt = client.prompts[0]
        self.assertIn("Skip the pep talk", prompt)
        self.assertNotIn("Sure, here is a plan", prompt)
        self.assertNotIn("file listing", prompt)

    def test_budget_stops_cleanly_and_leaves_the_session_for_next_time(self):
        budgeted = llm.BudgetedClient(FakeClient(reply(MEMORY)), llm.Budget(max_calls=0))
        report = self.run_sweep(budgeted)
        self.assertEqual((report.stopped, report.sessions_extracted), ("budget", 0))
        report = self.run_sweep(FakeClient(reply(MEMORY)))
        self.assertEqual(report.sessions_extracted, 1)

    def test_model_error_stops_the_sweep_and_is_reported(self):
        class Broken:
            def complete(self, prompt):
                raise llm.ModelError("Not logged in")

        report = self.run_sweep(Broken())
        self.assertEqual(report.stopped, "model_error: Not logged in")
        self.assertEqual(self.store.counts()["unconfirmed"], 0)

    def test_a_backlog_of_unreviewed_memories_never_stops_collection(self):
        for i in range(400):
            self.store.add(
                Memory(text=f"Old memory {i}", category="other", evidence=(Evidence("old", i, "q"),))
            )
        report = self.run_sweep(FakeClient(reply(MEMORY)))
        self.assertEqual(report.memories_new, 1)
        self.assertIsNone(report.stopped)

    def test_max_sessions_limits_new_work(self):
        shutil.copy(FIXTURE, self.tmp / "proj" / "two.jsonl")
        report = self.run_sweep(FakeClient(reply(MEMORY)), max_sessions=1)
        self.assertEqual((report.sessions_extracted, report.stopped), (1, "max_sessions"))


if __name__ == "__main__":
    unittest.main()
