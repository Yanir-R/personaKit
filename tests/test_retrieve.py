import unittest

from personakit import retrieve
from personakit.model import Evidence, Memory, State
from personakit.retrieve import SERVED, STANDING_CONTEXT, search


def mem(text, state=State.UNCONFIRMED, created="2026-01-01", category="other"):
    return Memory(text=text, category=category, state=state, created_at=created,
                  evidence=(Evidence("s", 0, "q"),))


class SearchTest(unittest.TestCase):
    def test_matching_memories_are_returned_best_overlap_first(self):
        a = mem("You use Python for data work.")
        b = mem("You use Python and Rust for data pipelines.")
        result = search([a, b], "python data pipelines")
        self.assertEqual([m.text for m in result.memories], [b.text, a.text])

    def test_approved_ranks_ahead_of_unconfirmed_on_equal_overlap(self):
        unconfirmed = mem("You like short answers.", created="2026-01-01")
        approved = mem("You like short replies.", state=State.APPROVED, created="2026-02-01")
        result = search([unconfirmed, approved], "short")
        self.assertEqual(result.memories[0], approved)

    def test_restricted_and_archived_are_never_served_and_restricted_matches_are_counted(self):
        restricted = mem("You are planning a job change.", state=State.RESTRICTED)
        archived = mem("You are planning a job change soon.", state=State.ARCHIVED)
        result = search([restricted, archived], "job change")
        self.assertEqual(result.memories, [])
        self.assertEqual(result.withheld, 1)

    def test_approved_standing_context_fills_when_little_matches(self):
        standing = [mem(f"Standing preference number {i}.", state=State.APPROVED, created=f"2026-01-0{i + 1}") for i in range(5)]
        unrelated_unconfirmed = mem("You collect stamps.")
        result = search(standing + [unrelated_unconfirmed], "completely different topic")
        self.assertEqual(len(result.memories), STANDING_CONTEXT)
        self.assertTrue(all(m.state == State.APPROVED for m in result.memories))

    def test_limit_is_respected(self):
        many = [mem(f"You like topic {i} apples.") for i in range(10)]
        self.assertEqual(len(search(many, "apples", limit=4).memories), 4)

    def test_only_approved_and_unconfirmed_are_ever_served(self):
        self.assertEqual(set(SERVED), {State.APPROVED, State.UNCONFIRMED})

    def test_stop_words_alone_do_not_match(self):
        self.assertEqual(search([mem("You prefer the quiet.")], "what should the").memories, [])


class ServedQuoteTest(unittest.TestCase):
    def test_served_quotes_mask_emails_and_end_at_a_word_boundary(self):
        self.assertEqual(retrieve.served_quote("write to me at someone@example.com please"),
                         "write to me at [email] please")
        long_quote = "word " * 100
        served = retrieve.served_quote(long_quote)
        self.assertLessEqual(len(served), retrieve.SERVED_QUOTE_CHARS + 1)
        self.assertTrue(served.endswith("word…"))
        first = "I like " + "very " * 25 + "direct feedback."
        self.assertEqual(retrieve.served_quote(first + " " + "filler " * 60), first)
        self.assertEqual(retrieve.served_quote("Short one."), "Short one.")


if __name__ == "__main__":
    unittest.main()
