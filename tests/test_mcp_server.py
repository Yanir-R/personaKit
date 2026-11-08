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

    def test_read_returns_served_memories_with_evidence_and_confirmation(self):
        result = mcp_server.read_memories(self.store, "how should I give feedback")
        (item,) = result["memories"]
        self.assertEqual(item["id"], self.approved.id)
        self.assertTrue(item["confirmed"])
        self.assertEqual(item["evidence"], ["Skip the pep talk."])

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


if __name__ == "__main__":
    unittest.main()
