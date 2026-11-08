import tempfile
import unittest
from pathlib import Path

from personakit.ingest import codex

FIXTURES = Path(__file__).parent / "fixtures" / "codex"


class ReadSessionTest(unittest.TestCase):
    def test_keeps_only_owner_messages(self):
        session = codex.read_session(FIXTURES / "rollout-basic.jsonl")
        self.assertEqual([t.text for t in session.turns], ["Prefer small, reviewable changes."])
        self.assertEqual(session.session_id, "c1")
        self.assertEqual(session.turns[0].source, "codex-cli")
        self.assertEqual(dict(session.dropped), {"scaffolding": 1, "paste": 1})

    def test_subagent_replayed_history_is_dropped_but_its_own_turns_are_kept(self):
        session = codex.read_session(FIXTURES / "rollout-subagent.jsonl")
        self.assertEqual([t.text for t in session.turns], ["The subagent's own user turn."])
        self.assertEqual(
            dict(session.dropped),
            {"subagent_replayed_history": 2, "subagent_unplaceable": 1},
        )


class DiscoverTest(unittest.TestCase):
    def test_finds_rollouts_year_month_day_deep_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = root / "2026" / "01" / "06"
            day.mkdir(parents=True)
            (day / "rollout-a.jsonl").write_text("{}\n")
            (day / "other.jsonl").write_text("{}\n")
            (root / "rollout-top.jsonl").write_text("{}\n")
            (root / "auth.json").write_text("{}")
            found = codex.discover(root)
        self.assertEqual([p.name for p in found], ["rollout-a.jsonl"])


if __name__ == "__main__":
    unittest.main()
