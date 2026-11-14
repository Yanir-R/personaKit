import unittest

from personakit.model import PROPOSED_BY_ASSISTANT, Decider, Evidence, Memory, State
from personakit.twins import find_twins, similarity


def mem(text, session="s1", category="communication", scope="global", state=State.UNCONFIRMED, created="2026-01-01T00:00:00Z"):
    return Memory(
        text=text,
        category=category,
        scope=scope,
        state=state,
        created_at=created,
        decided_by=Decider.OWNER if state != State.UNCONFIRMED else None,
        evidence=(Evidence(session, 0, "invented quote"),),
    )


class SimilarityTest(unittest.TestCase):
    def test_same_statement_worded_slightly_differently_matches(self):
        a = "You prefer direct, practical feedback."
        b = "You prefer direct and practical feedback from reviewers."
        self.assertGreaterEqual(similarity(a, b), 0.8)

    def test_plural_forms_count_as_the_same_word(self):
        self.assertEqual(similarity("You like short answers here.", "You like short answer here."), 1.0)

    def test_unrelated_texts_do_not_match(self):
        self.assertEqual(similarity("You prefer direct, practical feedback.", "You deploy services on Fridays."), 0.0)

    def test_different_numbers_are_never_twins(self):
        self.assertEqual(similarity("You indent code with 2 spaces.", "You indent code with 4 spaces."), 0.0)

    def test_negation_flips_the_meaning_so_they_are_never_twins(self):
        self.assertEqual(similarity("You use tabs for indentation.", "You do not use tabs for indentation."), 0.0)
        self.assertEqual(similarity("You like long meetings.", "You dislike long meetings."), 0.0)
        self.assertEqual(similarity("You use tabs for indentation.", "You don't use tabs for indentation."), 0.0)

    def test_swapped_order_is_not_a_twin(self):
        self.assertEqual(similarity("You prefer unit tests before integration tests.", "You prefer integration tests before unit tests."), 0.0)
        self.assertEqual(similarity("Prefers JS over TS for frontend projects at work", "Prefers TS over JS for frontend projects at work"), 0.0)

    def test_short_words_count(self):
        self.assertLess(similarity("You write backend services in Go.", "You write backend services in C."), 0.8)

    def test_negation_is_seen_with_any_apostrophe_and_any_contraction(self):
        plain = "Likes verbose commit messages in reviews"
        for negated in (
            "Doesn\u2019t like verbose commit messages in reviews",
            "Hasnt liked verbose commit messages in reviews",
            "Hadn't liked verbose commit messages in reviews",
        ):
            self.assertEqual(similarity(negated, plain), 0.0, negated)

    def test_number_words_count_like_digits(self):
        self.assertEqual(similarity("You live with two cats at home.", "You live with three cats at home."), 0.0)

    def test_extra_detail_is_not_a_twin(self):
        self.assertLess(similarity("You prefer short answers.", "You prefer short answers with examples."), 0.8)

    def test_too_few_shared_words_is_not_enough(self):
        self.assertEqual(similarity("You like tea.", "You like tea."), 0.0)


class FindTwinsTest(unittest.TestCase):
    def setUp(self):
        self.a = mem("You prefer direct, practical feedback.", created="2026-01-01T00:00:00Z")
        self.b = mem("You prefer direct and practical feedback from reviewers.", created="2026-01-02T00:00:00Z")

    def test_twins_from_the_same_session_are_grouped_with_the_oldest_kept(self):
        groups = find_twins([self.b, self.a])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].survivor.id, self.a.id)
        self.assertEqual([m.id for m in groups[0].duplicates], [self.b.id])

    def test_other_sessions_are_never_merged(self):
        other = mem(self.b.text, session="s2")
        self.assertEqual(find_twins([self.a, other]), [])

    def test_memory_resting_on_two_sessions_is_not_eligible(self):
        both = Memory(text=self.b.text, category="communication", evidence=(Evidence("s1", 0, "q"), Evidence("s2", 1, "q")))
        self.assertEqual(find_twins([self.a, both]), [])

    def test_assistant_proposals_are_never_merged(self):
        one = mem(self.a.text, session=PROPOSED_BY_ASSISTANT)
        two = mem(self.b.text, session=PROPOSED_BY_ASSISTANT)
        self.assertEqual(find_twins([one, two]), [])

    def test_owner_decisions_are_never_touched(self):
        for state in (State.APPROVED, State.RESTRICTED, State.ARCHIVED):
            self.assertEqual(find_twins([self.a, mem(self.b.text, state=state)]), [], state)

    def test_category_and_scope_must_match(self):
        self.assertEqual(find_twins([self.a, mem(self.b.text, category="tools")]), [])
        self.assertEqual(find_twins([self.a, mem(self.b.text, scope="work")]), [])

    def test_matching_is_against_the_anchor_so_groups_do_not_chain(self):
        # a~b and b~c but a is not close to c: c must not be pulled in through b.
        a = mem("You prefer short direct practical feedback notes.", created="2026-01-01T00:00:00Z")
        b = mem("You prefer short direct practical feedback notes always.", created="2026-01-02T00:00:00Z")
        c = mem("You prefer short direct practical feedback notes always daily reviews.", created="2026-01-03T00:00:00Z")
        groups = find_twins([a, b, c], threshold=0.75)
        self.assertEqual([[m.id for m in g.duplicates] for g in groups], [[b.id]])

    def test_vetoed_pair_is_not_proposed_again(self):
        self.assertEqual(find_twins([self.a, self.b], vetoed=frozenset({frozenset((self.a.id, self.b.id))})), [])

    def test_stricter_threshold_finds_fewer(self):
        self.assertEqual(find_twins([self.a, self.b], threshold=0.95), [])

    def test_result_does_not_depend_on_input_order(self):
        self.assertEqual(find_twins([self.a, self.b]), find_twins([self.b, self.a]))


if __name__ == "__main__":
    unittest.main()
