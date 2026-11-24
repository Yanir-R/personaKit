import asyncio
import json
import unittest

from personakit import mcp_server, stats
from personakit.model import Decider, Evidence, Memory, State
from personakit.store import Store

try:
    from mcp.server.fastmcp import FastMCP  # noqa: F401  (mcp 1.x; 2.x renamed it)
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


def seed(store):
    approved = Memory(text="You prefer direct, practical feedback.", category="communication",
                      evidence=(Evidence("s", 0, "Skip the pep talk."),))
    secret = Memory(text="You are planning a career change.", category="background",
                    evidence=(Evidence("s", 1, "I might quit."),))
    store.add(approved)
    store.add(secret)
    store.set_state(approved.id, State.APPROVED, Decider.OWNER)
    store.set_state(secret.id, State.RESTRICTED, Decider.OWNER)
    return approved, secret


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.approved, self.secret = seed(self.store)

    def test_read_returns_a_lean_packet_without_evidence_by_default(self):
        result = mcp_server.read_memories(self.store, "how should I give feedback")
        (item,) = result["memories"]
        self.assertEqual(item, {"id": self.approved.id, "text": self.approved.text,
                                "category": "communication", "confirmed": True})
        self.assertEqual((result["withheld"], result["more"]), (0, 0))

    def test_evidence_is_sent_only_when_asked_for(self):
        result = mcp_server.read_memories(self.store, "feedback", include_evidence=True)
        self.assertEqual(result["memories"][0]["evidence"], ["Skip the pep talk."])

    def test_owner_hints_are_used_for_ranking_but_never_sent(self):
        self.store.set_hints(self.approved.id, ["How do I review code?"], ["reviewing a pull request"])
        result = mcp_server.read_memories(self.store, "pull request review", include_evidence=True)
        self.assertEqual([m["id"] for m in result["memories"]], [self.approved.id])
        self.assertNotIn("pull request", json.dumps(result))
        self.assertNotIn("answers", result["memories"][0])

    def test_nothing_relevant_gives_an_empty_answer(self):
        result = mcp_server.read_memories(self.store, "zzzz unmatched topic")
        self.assertEqual((result["memories"], result["more"]), ([], 0))

    def test_more_and_context_and_scope_reach_the_read_policy(self):
        for i in range(3):
            self.store.add(Memory(text=f"You keep feedback notes, set {i}.", category="other",
                                  evidence=(Evidence("s", 10 + i, "Notes."),)))
        self.assertEqual(mcp_server.read_memories(self.store, "feedback", limit=2)["more"], 2)
        by_context = mcp_server.read_memories(self.store, "zzzz", context="giving practical feedback")
        self.assertEqual(len(by_context["memories"]), 4)
        self.store.add(Memory(text="You lint before pushing.", category="tools", scope="project-b",
                              evidence=(Evidence("s", 20, "Lint first."),)))
        self.assertEqual(mcp_server.read_memories(self.store, "lint", scope="project-a")["memories"], [])
        self.assertEqual(len(mcp_server.read_memories(self.store, "lint", scope="project-b")["memories"]), 1)


class SeenTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.approved, _ = seed(self.store)
        self.seen = set()

    def read(self, **options):
        return mcp_server.read_memories(self.store, "feedback", seen=self.seen, **options)

    def test_a_memory_sent_in_full_comes_back_as_its_id_only(self):
        first = self.read()
        self.assertIn("text", first["memories"][0])
        self.assertNotIn("seen_note", first)
        self.assertEqual(self.seen, {self.approved.id})
        again = self.read()
        self.assertEqual(again["memories"], [{"id": self.approved.id, "seen": True}])
        self.assertEqual(again["seen_note"], mcp_server.NOTE_SEEN)

    def test_include_seen_or_evidence_sends_it_in_full_again(self):
        self.read()
        self.assertEqual(self.read(include_seen=True)["memories"][0]["text"], self.approved.text)
        with_quotes = self.read(include_evidence=True)["memories"][0]
        self.assertEqual(with_quotes["evidence"], ["Skip the pep talk."])

    def test_unconfirmed_note_follows_only_full_entries(self):
        extra = Memory(text="You prefer short feedback.", category="communication",
                       evidence=(Evidence("s", 2, "Keep it short."),))
        self.store.add(extra)
        self.assertIn("note", self.read())
        self.assertNotIn("note", self.read())

    def test_without_a_set_every_read_is_in_full(self):
        mcp_server.read_memories(self.store, "feedback")
        self.assertIn("text", mcp_server.read_memories(self.store, "feedback")["memories"][0])

    def test_unconfirmed_note_only_when_an_unconfirmed_memory_is_served(self):
        confirmed_only = mcp_server.read_memories(self.store, "how should I give feedback")
        self.assertNotIn("note", confirmed_only)
        extra = Memory(text="You prefer short answers.", category="communication",
                       evidence=(Evidence("s", 2, "Keep it short."),))
        self.store.add(extra)
        mixed = mcp_server.read_memories(self.store, "feedback and short answers")
        self.assertEqual(mixed["note"], mcp_server.NOTE_UNCONFIRMED)

    def test_restricted_text_never_appears_in_the_response(self):
        result = mcp_server.read_memories(self.store, "career change quit")
        self.assertNotIn("career", str(result))
        self.assertEqual(result["withheld"], 1)

    def test_reads_are_logged_as_counts_only(self):
        mcp_server.read_memories(self.store, "feedback")
        mcp_server.read_memories(self.store, "zzzz unmatched topic")
        self.assertEqual(stats.collect(self.store)["reads"], 2)

    def test_limit_is_clamped(self):
        self.assertLessEqual(len(mcp_server.read_memories(self.store, "feedback", limit=-5)["memories"]), 1)


class ProposeTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def test_proposing_an_archived_statement_does_not_bring_it_back(self):
        memory = Memory(text="You use Rust for tools.", category="tools", evidence=(Evidence("s1", 0, "I write Rust."),))
        self.store.add(memory)
        self.store.set_state(memory.id, State.ARCHIVED, Decider.POLICY)
        before = self.store.get(memory.id).last_seen_at
        result = mcp_server.propose_memory(self.store, memory.text, "anything")
        self.assertFalse(result["new"])
        after = self.store.get(memory.id)
        self.assertEqual((after.state, after.last_seen_at), (State.ARCHIVED, before))
        self.assertEqual(mcp_server.read_memories(self.store, "rust tools")["memories"], [])

    def test_proposal_is_stored_unconfirmed_and_marked_as_assistant_proposed(self):
        result = mcp_server.propose_memory(self.store, "You use Rust.", "I write Rust daily", "tools")
        self.assertTrue(result["stored"])
        memory = self.store.get(result["id"])
        self.assertEqual(memory.state, State.UNCONFIRMED)
        self.assertEqual(memory.evidence[0].session_id, "mcp-proposal")

    def test_bad_proposals_are_refused(self):
        key = "sk-" + "ant-abcdefghijklmnop"
        for text, quote in (("", "q"), ("x" * 400, "q"), (f"Key {key}", "q"), ("You use Rust.", "  ")):
            self.assertFalse(mcp_server.propose_memory(self.store, text, quote)["stored"])
        self.assertEqual(self.store.counts()["unconfirmed"], 0)

    def test_assistants_have_no_way_to_decide(self):
        names = [n for n in dir(mcp_server) if not n.startswith("_")]
        self.assertFalse([n for n in names if "approve" in n or "forget" in n or "decide" in n])


@unittest.skipUnless(HAVE_MCP, "mcp 1.x not installed")
class ServerTest(unittest.TestCase):
    def test_server_exposes_exactly_read_and_propose(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        seed(store)
        server = mcp_server.build_server(store)
        tools = asyncio.run(server.list_tools())
        self.assertEqual(sorted(t.name for t in tools), ["personakit_propose", "personakit_read"])
        content = asyncio.run(server.call_tool("personakit_read", {"question": "feedback"}))
        content = content[0] if isinstance(content, tuple) else content  # (content, structured) in some 1.x
        result = json.loads(content[0].text)
        self.assertEqual(result["memories"][0]["text"], "You prefer direct, practical feedback.")
        self.assertNotIn("evidence", result["memories"][0])

    def test_one_server_remembers_what_it_sent_and_a_new_server_starts_fresh(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        seed(store)

        def read(server, **args):
            content = asyncio.run(server.call_tool("personakit_read", {"question": "feedback", **args}))
            content = content[0] if isinstance(content, tuple) else content
            return json.loads(content[0].text)["memories"][0]

        server = mcp_server.build_server(store)
        self.assertIn("text", read(server, context="writing a review"))
        self.assertEqual(read(server).get("seen"), True)
        self.assertIn("evidence", read(server, include_evidence=True))
        self.assertIn("text", read(mcp_server.build_server(store)))

    def test_select_hears_the_name_the_assistant_connected_with(self):
        from mcp import types
        from mcp.shared.memory import create_connected_server_and_client_session

        store = Store(":memory:")
        self.addCleanup(store.close)
        seed(store)
        heard = []

        def select(question, context, memories, client):
            heard.append(client)
            return None

        server = mcp_server.build_server(store, select=select)

        async def run():
            info = types.Implementation(name="claude-code", version="1.0")
            async with create_connected_server_and_client_session(server._mcp_server, client_info=info) as session:
                await session.call_tool("personakit_read", {"question": "feedback"})

        asyncio.run(run())
        self.assertEqual(heard, ["claude-code"])


if __name__ == "__main__":
    unittest.main()
