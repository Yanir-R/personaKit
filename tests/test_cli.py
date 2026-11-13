import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from personakit import cli, llm
from personakit.model import Evidence, Memory
from personakit.store import Store
from tests.helpers import reply

FIXTURES = Path(__file__).parent / "fixtures" / "claude_code"
MEMORY = {"text": "You prefer direct, practical feedback.", "category": "communication", "turns": [0, 2]}


class FakeCli:
    last = None

    def __init__(self, model):
        self.model = model
        FakeCli.last = self

    def complete(self, prompt):
        return reply(MEMORY)


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp)
        self.db = self.tmp / "nested" / "store.db"

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--db", str(self.db), *argv])
        return code, out.getvalue(), err.getvalue()


class CliTest(CliCase):
    def test_sweep_then_list_stats_and_forget(self):
        root = self.tmp / "projects"
        (root / "proj").mkdir(parents=True)
        (root / "proj" / "one.jsonl").write_text((FIXTURES / "session.jsonl").read_text())
        with mock.patch.dict(cli.CLIENTS, {"claude": FakeCli}):
            code, out, _ = self.run_cli("sweep", "--source", "claude-code", "--model", "m", "--root", str(root))
        self.assertEqual(code, 0)
        self.assertIn("1 extracted", out)
        self.assertEqual(FakeCli.last.model, "m")

        _, listing, _ = self.run_cli("list")
        self.assertIn("unconfirmed", listing)
        memory_id = listing.split()[0]

        _, stats_out, _ = self.run_cli("stats")
        self.assertIn("memories_unconfirmed: 1", stats_out)
        self.assertNotIn("practical", stats_out)

        self.assertEqual(self.run_cli("forget", memory_id)[0], 0)
        self.assertEqual(self.run_cli("forget", memory_id)[0], 1)

    def test_json_outputs_are_structured_and_repeatable(self):
        root = self.tmp / "projects"
        (root / "proj").mkdir(parents=True)
        (root / "proj" / "one.jsonl").write_text((FIXTURES / "session.jsonl").read_text())
        with mock.patch.dict(cli.CLIENTS, {"claude": FakeCli}):
            _, swept, _ = self.run_cli(
                "sweep", "--source", "claude-code", "--model", "m", "--root", str(root), "--json"
            )
        report = json.loads(swept)
        self.assertEqual(report["source"], "claude-code")
        self.assertEqual(report["sessions_extracted"], 1)
        self.assertEqual(report["memories_new"], 1)
        self.assertIsNone(report["stopped"])

        _, listing, _ = self.run_cli("list", "--json")
        (row,) = json.loads(listing)
        self.assertEqual(row["state"], "unconfirmed")
        self.assertEqual(row["text"], MEMORY["text"])
        self.assertEqual(row["quotes"], 2)
        self.assertNotIn("quote", {k for k in row if k != "quotes"})
        self.assertEqual(self.run_cli("list", "--json")[1], listing)

        _, stats_out, _ = self.run_cli("stats", "--json")
        self.assertEqual(json.loads(stats_out)["memories_unconfirmed"], 1)
        self.assertEqual(self.run_cli("stats", "--json")[1], stats_out)

    def test_model_is_required(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            cli.main(["--db", str(self.db), "sweep"])

    def test_root_requires_a_single_source(self):
        code, _, err = self.run_cli("sweep", "--model", "m", "--root", str(self.tmp))
        self.assertEqual(code, 2)
        self.assertIn("single --source", err)

    def test_model_error_gives_nonzero_exit(self):
        root = self.tmp / "projects"
        (root / "proj").mkdir(parents=True)
        (root / "proj" / "one.jsonl").write_text((FIXTURES / "session.jsonl").read_text())

        class Broken(FakeCli):
            def complete(self, prompt):
                raise llm.ModelError("Not logged in")

        with mock.patch.dict(cli.CLIENTS, {"claude": Broken}):
            code, out, _ = self.run_cli("sweep", "--source", "claude-code", "--model", "m", "--root", str(root))
        self.assertEqual(code, 1)
        self.assertIn("Not logged in", out)

    def test_db_defaults_to_environment_variable(self):
        with mock.patch.dict("os.environ", {"PERSONAKIT_DB": str(self.db)}):
            self.assertEqual(cli.default_db(), self.db)


class TidyCliTest(CliCase):
    """tidy, undo, merges and digest, on a store seeded with invented memories dated long ago."""

    def seed(self):
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.clock = ["2020-01-01T00:00:00Z"]
        with Store(self.db, now=lambda: self.clock[0]) as store:
            for turn, text in enumerate(
                ["You prefer direct, practical feedback.", "You prefer direct and practical feedback from reviewers."]
            ):
                self.clock[0] = f"2020-01-01T00:00:0{turn}Z"
                store.add(Memory(text=text, category="communication", evidence=(Evidence("s1", turn, "q"),)))

    def test_tidy_shows_a_plan_and_changes_nothing_until_applied(self):
        self.seed()
        code, out, _ = self.run_cli("tidy", "--only", "merge")
        self.assertEqual(code, 0)
        self.assertIn("1 to merge, 0 to archive. Nothing changed", out)
        self.assertEqual(self.run_cli("merges")[1], "")

    def test_apply_then_list_merges_then_undo(self):
        self.seed()
        _, out, _ = self.run_cli("tidy", "--apply", "--only", "merge")
        self.assertIn("Merged 1, archived 0", out)
        _, merges, _ = self.run_cli("merges")
        duplicate_id = merges.split()[0]
        self.assertEqual(len(json.loads(self.run_cli("list", "--json")[1])), 1)
        code, out, _ = self.run_cli("undo", duplicate_id)
        self.assertEqual((code, out), (0, "Unmerged.\n"))
        self.assertEqual(len(json.loads(self.run_cli("list", "--json")[1])), 2)
        self.assertEqual(self.run_cli("undo", duplicate_id)[0], 1)

    def test_old_unconfirmed_memories_are_archived_and_can_be_restored(self):
        self.seed()
        _, out, _ = self.run_cli("tidy", "--apply", "--only", "archive", "--days", "30")
        self.assertIn("Merged 0, archived 2", out)
        listing = json.loads(self.run_cli("list", "--state", "archived", "--json")[1])
        self.assertEqual(len(listing), 2)
        self.assertEqual(self.run_cli("undo", listing[0]["id"])[1], "Restored.\n")

    def test_tidy_json_lists_ids_only(self):
        self.seed()
        _, out, _ = self.run_cli("tidy", "--json", "--days", "30")
        data = json.loads(out)
        self.assertFalse(data["applied"])
        self.assertEqual(len(data["merge"][0]["fold"]), 1)
        self.assertNotIn("prefer", out)

    def test_nothing_to_tidy_on_a_fresh_store(self):
        self.assertIn("Nothing to tidy.", self.run_cli("tidy")[1])

    def test_tidy_rejects_bad_numbers(self):
        self.assertEqual(self.run_cli("tidy", "--days", "0")[0], 2)
        self.assertEqual(self.run_cli("tidy", "--threshold", "1.5")[0], 2)

    def test_digest_prints_text_or_json(self):
        self.seed()
        _, text, _ = self.run_cli("digest")
        self.assertIn("PersonaKit digest, last 7 days", text)
        data = json.loads(self.run_cli("digest", "--days", "99999", "--json")[1])
        self.assertEqual(data["new"], 2)


if __name__ == "__main__":
    unittest.main()
