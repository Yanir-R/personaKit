import unittest

from personakit import digest, tidy
from personakit.model import Evidence, Memory
from personakit.store import Store

NOW = "2026-06-01T00:00:00Z"


def mem(text, turn=0):
    return Memory(text=text, category="other", evidence=(Evidence("s1", turn, f"quote {turn}"),))


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.clock = ["2026-01-01T00:00:00Z"]
        self.store = Store(":memory:", now=lambda: self.clock[0])
        self.addCleanup(self.store.close)

    def test_digest_covers_only_the_window_and_lists_ids_with_text(self):
        self.store.add(mem("You are an old memory about tabs."))
        self.store.log_read(1, 0)
        self.clock[0] = "2026-05-30T00:00:00Z"
        recent = mem("You prefer direct, practical feedback.", turn=1)
        self.store.add(recent)
        self.store.log_read(2, 0)
        self.store.log_read(0, 0)
        data = digest.collect(self.store, NOW, days=7)
        self.assertEqual((data["new"], data["reads"], data["reads_with_results"], data["awaiting_review"]), (1, 2, 1, 2))
        self.assertEqual(data["new_items"], [{"id": recent.id, "text": recent.text}])
        text = digest.format_digest(data)
        self.assertIn(recent.id, text)
        self.assertIn("Awaiting your review: 2", text)
        self.assertNotIn("quote", text)

    def test_digest_shows_what_decay_archived_and_caps_long_lists(self):
        for i in range(digest.LISTED + 2):
            self.store.add(mem(f"You track item number {i} in notes.", turn=i))
        self.clock[0] = NOW
        tidy.apply(self.store, tidy.make_plan(self.store, NOW, days=30))
        data = digest.collect(self.store, NOW, days=7)
        self.assertEqual((data["archived_by_decay"], len(data["archived_items"])), (digest.LISTED + 2, digest.LISTED))
        self.assertIn("... and 2 more", digest.format_digest(data))


if __name__ == "__main__":
    unittest.main()
