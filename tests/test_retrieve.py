import unittest

from personakit import retrieve
from personakit.model import Evidence, Memory, State
from personakit.retrieve import SERVED, search


def mem(text, state=State.UNCONFIRMED, created="2026-01-01", category="other", scope="global", **hints):
    return Memory(text=text, category=category, state=state, created_at=created, scope=scope,
                  evidence=(Evidence("s", 0, "q"),), **hints)


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

    def test_nothing_relevant_means_an_empty_result_even_with_approved_memories(self):
        approved = [mem(f"Standing preference number {i}.", state=State.APPROVED) for i in range(5)]
        result = search(approved + [mem("You collect stamps.")], "completely different topic")
        self.assertEqual((result.memories, result.withheld, result.more), ([], 0, 0))

    def test_more_counts_relevant_servable_memories_left_out_by_the_limit(self):
        many = [mem(f"You like topic {i} apples.") for i in range(6)]
        hidden = [mem("You grow apples secretly.", state=State.RESTRICTED), mem("You sold apples.", state=State.ARCHIVED)]
        result = search(many + hidden + [mem("You like pears.")], "apples", limit=4)
        self.assertEqual((len(result.memories), result.more, result.withheld), (4, 2, 1))
        self.assertEqual(search(many, "apples", limit=10).more, 0)

    def test_context_is_scored_separately_and_the_better_score_counts(self):
        tests = mem("You always write tests before a refactor.")
        tabs = mem("You indent with tabs.")
        calls = []

        def relevance(text, memories):
            calls.append(text)
            return retrieve.overlap(text, memories)

        result = search([tests, tabs], "indent style", relevance=relevance, context="about to refactor the parser")
        self.assertEqual(calls, ["indent style", "about to refactor the parser"])
        self.assertEqual(set(result.memories), {tests, tabs})
        self.assertEqual(search([tests, tabs], "indent style").memories, [tabs])

    def test_blank_context_does_not_call_relevance_again(self):
        calls = []
        search([mem("You like tea.")], "tea", relevance=lambda q, ms: calls.append(q) or [1.0] * len(ms), context="  ")
        self.assertEqual(calls, ["tea"])

    def test_scope_keeps_global_and_matching_memories_only(self):
        general = mem("You like terse commit messages.")
        here = mem("You run the commit hooks in this project.", scope="project-a")
        elsewhere = mem("You squash every commit there.", scope="project-b")
        secret = mem("You commit late at night.", scope="project-b", state=State.RESTRICTED)
        unscoped = search([general, here, elsewhere, secret], "commit")
        self.assertEqual((len(unscoped.memories), unscoped.withheld), (3, 1))
        scoped = search([general, here, elsewhere, secret], "commit", scope="project-a")
        self.assertEqual((set(scoped.memories), scoped.withheld), ({general, here}, 0))

    def test_owner_hints_count_towards_word_overlap(self):
        hinted = mem("You prefer short replies.", answers=("How long should answers be?",),
                     applies_when=("writing release notes",))
        self.assertEqual(search([hinted], "release notes").memories, [hinted])
        self.assertEqual(search([hinted], "answers length").memories, [hinted])
        self.assertEqual(search([mem("You prefer short replies.")], "release notes").memories, [])

    def test_limit_is_respected(self):
        many = [mem(f"You like topic {i} apples.") for i in range(10)]
        self.assertEqual(len(search(many, "apples", limit=4).memories), 4)

    def test_only_approved_and_unconfirmed_are_ever_served(self):
        self.assertEqual(set(SERVED), {State.APPROVED, State.UNCONFIRMED})

    def test_stop_words_alone_do_not_match(self):
        self.assertEqual(search([mem("You prefer the quiet.")], "what should the").memories, [])


class SelectTest(unittest.TestCase):
    """A select hook sees only what may be served, once per read, and can only narrow it."""

    def setUp(self):
        self.a = mem("You use Python and Rust for data pipelines.")
        self.b = mem("You use Python for data work.")
        self.c = mem("You use Python at home.", state=State.APPROVED)
        self.restricted = mem("You use Python for a secret project.", state=State.RESTRICTED)
        self.archived = mem("You used Python for data long ago.", state=State.ARCHIVED)
        self.calls = []

    def search(self, picked, **kw):
        def select(question, context, memories, client):
            self.calls.append((question, context, list(memories), client))
            return picked(memories) if callable(picked) else picked
        pool = [self.a, self.b, self.c, self.restricted, self.archived]
        return search(pool, "python data pipelines", select=select, **kw)

    def test_select_sees_only_relevant_servable_memories_best_first_once(self):
        self.search(None, context="writing a script", client="claude-code")
        self.assertEqual(len(self.calls), 1)
        question, context, offered, client = self.calls[0]
        self.assertEqual((question, context, client), ("python data pipelines", "writing a script", "claude-code"))
        self.assertEqual(offered[0], self.a)
        self.assertNotIn(self.restricted, offered)
        self.assertNotIn(self.archived, offered)

    def test_none_leaves_the_read_unchanged(self):
        self.assertEqual(self.search(None).memories, search([self.a, self.b, self.c], "python data pipelines").memories)

    def test_select_narrows_and_the_order_stays_the_cores(self):
        result = self.search(lambda offered: [offered[2], offered[0]])
        offered = self.calls[0][2]
        self.assertEqual(result.memories, [offered[0], offered[2]])

    def test_select_cannot_widen(self):
        result = self.search([self.b, self.restricted, self.archived, mem("You use Go.")])
        self.assertEqual(result.memories, [self.b])
        self.assertEqual(result.withheld, 1)

    def test_an_empty_selection_serves_nothing_and_more_counts_after_it(self):
        self.assertEqual(self.search([]).memories, [])
        result = self.search(lambda offered: offered[:2], limit=1)
        self.assertEqual((len(result.memories), result.more), (1, 1))

    def test_no_relevant_memory_means_select_is_not_called(self):
        search([self.a], "unrelated words entirely", select=lambda *a: self.calls.append(a))
        self.assertEqual(self.calls, [])


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
