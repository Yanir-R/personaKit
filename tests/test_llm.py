import json
import subprocess
import unittest
from pathlib import Path

from personakit import llm
from personakit.ingest.common import SANDBOX_PREFIX


def proc(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class Recorder:
    """A runner that records what it was given and returns a canned process."""

    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, argv, stdin, cwd, timeout):
        self.calls.append({"argv": argv, "stdin": stdin, "cwd": cwd, "timeout": timeout,
                           "cwd_existed": Path(cwd).is_dir()})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class ClaudeCliTest(unittest.TestCase):
    def client(self, result):
        runner = Recorder(result)
        return llm.ClaudeCli("some-model", runner=runner), runner

    def test_returns_the_result_field_of_the_envelope(self):
        client, _ = self.client(proc(json.dumps({"result": "hello"})))
        self.assertEqual(client.complete("prompt"), "hello")

    def test_prompt_goes_on_stdin_never_in_argv(self):
        client, runner = self.client(proc(json.dumps({"result": "ok"})))
        client.complete("SECRET-OWNER-TEXT")
        call = runner.calls[0]
        self.assertEqual(call["stdin"], "SECRET-OWNER-TEXT")
        self.assertFalse(any("SECRET-OWNER-TEXT" in a for a in call["argv"]))

    def test_tools_are_off_and_model_is_explicit(self):
        client, runner = self.client(proc(json.dumps({"result": "ok"})))
        client.complete("p")
        argv = runner.calls[0]["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--model") + 1], "some-model")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)

    def test_runs_in_a_marked_sandbox_that_is_removed_afterwards(self):
        client, runner = self.client(proc(json.dumps({"result": "ok"})))
        client.complete("p")
        call = runner.calls[0]
        self.assertTrue(Path(call["cwd"]).name.startswith(SANDBOX_PREFIX))
        self.assertTrue(call["cwd_existed"])
        self.assertFalse(Path(call["cwd"]).exists())

    def test_error_envelope_raises_even_when_exit_code_is_nonzero(self):
        client, _ = self.client(proc(json.dumps({"is_error": True, "result": "Not logged in"}), 1))
        with self.assertRaisesRegex(llm.ModelError, "Not logged in"):
            client.complete("p")

    def test_missing_result_and_bad_exit_raise(self):
        for result in (proc("not json"), proc(json.dumps({"x": 1})), proc("{}", 2)):
            client, _ = self.client(result)
            with self.assertRaises(llm.ModelError):
                client.complete("p")

    def test_missing_executable_and_timeout_become_model_errors(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("claude", 1)):
            client, _ = self.client(error)
            with self.assertRaises(llm.ModelError):
                client.complete("p")

    def test_model_name_is_required(self):
        with self.assertRaises(ValueError):
            llm.ClaudeCli("")


class CodexCliTest(unittest.TestCase):
    def test_returns_the_last_completed_agent_message(self):
        events = [
            "Reading additional input from stdin...",
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
            json.dumps({"type": "item.completed", "item": {"type": "reasoning", "text": "no"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "final"}}),
        ]
        runner = Recorder(proc("\n".join(events)))
        client = llm.CodexCli("m", runner=runner)
        self.assertEqual(client.complete("p"), "final")
        argv = runner.calls[0]["argv"]
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(runner.calls[0]["stdin"], "p")

    def test_no_agent_message_or_bad_exit_raises(self):
        for result in (proc(""), proc("{}", 1)):
            with self.assertRaises(llm.ModelError):
                llm.CodexCli("m", runner=Recorder(result)).complete("p")


class BudgetTest(unittest.TestCase):
    def test_stops_after_max_calls(self):
        inner = type("C", (), {"complete": lambda self, p: "ok"})()
        client = llm.BudgetedClient(inner, llm.Budget(max_calls=2))
        client.complete("a")
        client.complete("b")
        with self.assertRaises(llm.BudgetExceeded):
            client.complete("c")


if __name__ == "__main__":
    unittest.main()
