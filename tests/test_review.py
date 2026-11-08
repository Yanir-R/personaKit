import unittest

from personakit import review
from personakit.model import Evidence, Memory, State
from personakit.store import Store


def add(store, text, session="s1"):
    memory = Memory(text=text, category="other", evidence=(Evidence(session, 0, f"quote for {text}"),),)
    store.add(memory)
    return memory


class Script:
    """Feeds scripted answers to the review loop and records its output."""

    def __init__(self, *answers):
        self.answers, self.out = list(answers), []

    def input(self, prompt):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def output(self, text):
        self.out.append(text)


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.a, self.b, self.c, self.d = (add(self.store, t) for t in ("alpha", "bravo", "charlie", "delta"))

    def run_review(self, *answers, limit=10):
        script = Script(*answers)
        summary = review.run_review(self.store, script.input, script.output, limit)
        return summary, script

    def test_each_choice_moves_the_memory_and_records_the_owner(self):
        summary, _ = self.run_review("a", "r", "h", "s")
        states = {m.text: m.state for m in self.store.list()}
        self.assertEqual(states, {"alpha": State.APPROVED, "bravo": State.RESTRICTED,
                                  "charlie": State.ARCHIVED, "delta": State.UNCONFIRMED})
        self.assertEqual(self.store.get(self.a.id).decided_by.value, "owner")
        self.assertEqual((summary.approved, summary.restricted, summary.hidden, summary.skipped), (1, 1, 1, 1))

    def test_forget_needs_confirmation(self):
        self.run_review("f", "n", "f", "y")
        self.assertIsNotNone(self.store.get(self.a.id))
        self.assertIsNone(self.store.get(self.b.id))

    def test_quit_stops_and_reports_what_is_left(self):
        summary, script = self.run_review("a", "q")
        self.assertEqual(summary.remaining, 3)
        self.assertIn("3 still unconfirmed", script.out[-1])

    def test_invalid_answers_are_asked_again(self):
        summary, script = self.run_review("zzz", "a", "q")
        self.assertEqual(summary.approved, 1)
        self.assertTrue(any("Please answer" in line for line in script.out))

    def test_end_of_input_is_quit(self):
        summary, _ = self.run_review()
        self.assertEqual(summary.remaining, 4)

    def test_limit_caps_the_session_but_not_the_remaining_count(self):
        summary, _ = self.run_review("a", "a", limit=2)
        self.assertEqual((summary.approved, summary.remaining), (2, 2))

    def test_empty_queue(self):
        empty = Store(":memory:")
        self.addCleanup(empty.close)
        script = Script()
        review.run_review(empty, script.input, script.output)
        self.assertEqual(script.out, ["Nothing to review."])

    def test_assistant_proposals_are_labelled(self):
        proposal = add(self.store, "echo", session=review.PROPOSED_BY_ASSISTANT)
        text = review.describe(self.store.get(proposal.id), 1, 1)
        self.assertIn("proposed by an assistant", text)


if __name__ == "__main__":
    unittest.main()
