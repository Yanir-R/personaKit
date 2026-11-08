import tempfile
import unittest
from pathlib import Path

from personakit.ingest import claude_code

FIXTURES = Path(__file__).parent / "fixtures" / "claude_code"


class ReadSessionTest(unittest.TestCase):
    def setUp(self):
        self.session = claude_code.read_session(FIXTURES / "session.jsonl")

    def test_keeps_only_what_the_owner_wrote(self):
        self.assertEqual(
            [t.text for t in self.session.turns],
            [
                "Skip the pep talk. Give me the practical next step.",
                "Please keep answers short.",
                "If you disagree, tell me why.",
            ],
        )

    def test_turns_are_numbered_in_order_with_session_metadata(self):
        self.assertEqual([t.index for t in self.session.turns], [0, 1, 2])
        self.assertEqual({t.session_id for t in self.session.turns}, {"session"})
        self.assertEqual(self.session.turns[0].timestamp, "2026-01-05T09:00:00Z")
        self.assertEqual(self.session.turns[0].source, "claude-code")

    def test_every_drop_is_counted_by_reason(self):
        self.assertEqual(
            dict(self.session.dropped),
            {
                "tool_result": 1,
                "harness": 1,
                "scaffolding": 1,
                "paste": 1,
                "sidechain": 1,
                "unparsable_line": 1,
            },
        )

    def test_assistant_text_is_never_returned(self):
        self.assertFalse(any("Sure, here is a plan" in t.text for t in self.session.turns))

    def test_headless_session_is_dropped_whole(self):
        session = claude_code.read_session(FIXTURES / "headless.jsonl")
        self.assertEqual(session.turns, [])
        self.assertEqual(dict(session.dropped), {"machine_session": 1})

    def test_session_started_in_extraction_sandbox_is_dropped_whole(self):
        session = claude_code.read_session(FIXTURES / "sandbox.jsonl")
        self.assertEqual(session.turns, [])
        self.assertEqual(dict(session.dropped), {"machine_session": 1})


class DiscoverTest(unittest.TestCase):
    def test_finds_only_top_level_session_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "proj-a").mkdir()
            (root / "proj-a" / "one.jsonl").write_text("{}\n")
            (root / "proj-a" / "notes.md").write_text("x")
            (root / "proj-a" / "one" / "subagents").mkdir(parents=True)
            (root / "proj-a" / "one" / "subagents" / "agent.jsonl").write_text("{}\n")
            (root / "stray.jsonl").write_text("{}\n")
            found = claude_code.discover(root)
        self.assertEqual([p.name for p in found], ["one.jsonl"])

    def test_missing_root_is_empty(self):
        self.assertEqual(claude_code.discover(Path("/nonexistent/personakit-test")), [])


if __name__ == "__main__":
    unittest.main()
