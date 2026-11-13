import unittest

from personakit.decay import days_ago, find_stale
from personakit.model import Decider, Evidence, Memory, State

NOW = "2026-06-01T00:00:00Z"


def mem(text, state=State.UNCONFIRMED, created="2026-01-01T00:00:00Z", seen=None):
    return Memory(
        text=text,
        category="other",
        state=state,
        created_at=created,
        last_seen_at=seen,
        decided_by=Decider.OWNER if state != State.UNCONFIRMED else None,
        evidence=(Evidence("s", 0, "q"),),
    )


class DecayTest(unittest.TestCase):
    def test_days_ago_counts_back_from_now(self):
        self.assertEqual(days_ago(NOW, 7), "2026-05-25T00:00:00Z")

    def test_old_unconfirmed_memory_is_stale(self):
        self.assertEqual([m.text for m in find_stale([mem("old")], NOW, 90)], ["old"])

    def test_recently_seen_memory_is_not_stale_even_if_created_long_ago(self):
        self.assertEqual(find_stale([mem("again", seen="2026-05-20T00:00:00Z")], NOW, 90), [])

    def test_owner_decisions_never_decay(self):
        kept = [mem("a", State.APPROVED), mem("r", State.RESTRICTED), mem("h", State.ARCHIVED)]
        self.assertEqual(find_stale(kept, NOW, 90), [])

    def test_boundary_is_exclusive(self):
        edge = mem("edge", seen=days_ago(NOW, 90))
        self.assertEqual(find_stale([edge], NOW, 90), [])

    def test_days_must_be_positive(self):
        with self.assertRaises(ValueError):
            find_stale([], NOW, 0)


if __name__ == "__main__":
    unittest.main()
