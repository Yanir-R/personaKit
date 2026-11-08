"""The only module that talks to a model.

A client has one method, ``complete(prompt) -> str``. The two CLI clients run a model you are
already signed in to (``claude`` or ``codex``) with every tool turned off, in an empty temporary
directory, with the prompt on stdin so it never appears in the process list. The model is always
named by the caller; nothing is defaulted.

Note: the argument lists below follow the documented flags of those CLIs but have only been
exercised here through an injected runner. Run a real extraction once before relying on them.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from personakit.ingest.common import SANDBOX_PREFIX

DEFAULT_TIMEOUT_SECONDS = 300

SYSTEM_PROMPT = (
    "You extract short memories about the user from their own messages. "
    "Reply with the JSON object the instructions ask for and nothing else."
)


class ModelError(RuntimeError):
    """The model call failed (not logged in, timed out, bad output envelope)."""


class BudgetExceeded(ModelError):
    """The configured call budget is used up. The caller should stop cleanly."""


class ModelClient(Protocol):
    def complete(self, prompt: str) -> str: ...


# argv, stdin text, working directory, timeout seconds -> finished process
Runner = Callable[[list[str], str, Path, int], "subprocess.CompletedProcess[str]"]


def run_subprocess(argv: list[str], stdin: str, cwd: Path, timeout: int):
    return subprocess.run(
        argv, input=stdin, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


@dataclass
class Budget:
    """A cap on how many model calls one run may make."""

    max_calls: int
    used: int = 0

    def charge(self) -> None:
        if self.used >= self.max_calls:
            raise BudgetExceeded(f"call budget of {self.max_calls} reached")
        self.used += 1


class BudgetedClient:
    def __init__(self, client: ModelClient, budget: Budget):
        self._client = client
        self._budget = budget

    def complete(self, prompt: str) -> str:
        self._budget.charge()
        return self._client.complete(prompt)


class _CliClient:
    executable = ""

    def __init__(
        self,
        model: str,
        runner: Runner = run_subprocess,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        executable: str | None = None,
    ):
        if not model:
            raise ValueError("a model name is required")
        self.model = model
        self._runner = runner
        self._timeout = timeout
        if executable:
            self.executable = executable

    def complete(self, prompt: str) -> str:
        # The directory name marks any session this call creates as machine-authored,
        # so ingest never mistakes our own prompts for the owner's words.
        with tempfile.TemporaryDirectory(prefix=SANDBOX_PREFIX) as tmp:
            cwd = Path(tmp)
            argv = self._argv(cwd)
            try:
                proc = self._runner(argv, prompt, cwd, self._timeout)
            except FileNotFoundError as exc:
                raise ModelError(f"{argv[0]} was not found on PATH") from exc
            except subprocess.TimeoutExpired as exc:
                raise ModelError(f"{argv[0]} timed out after {self._timeout}s") from exc
            return self._reply(proc)

    def _argv(self, cwd: Path) -> list[str]:
        raise NotImplementedError

    def _reply(self, proc) -> str:
        raise NotImplementedError


class ClaudeCli(_CliClient):
    executable = "claude"

    def _argv(self, cwd: Path) -> list[str]:
        empty_mcp = cwd / "mcp.json"
        empty_mcp.write_text('{"mcpServers": {}}')
        return [
            self.executable, "-p", "--output-format", "json",
            "--tools", "",
            "--setting-sources", "",
            "--strict-mcp-config", "--mcp-config", str(empty_mcp),
            "--disable-slash-commands", "--no-session-persistence",
            "--system-prompt", SYSTEM_PROMPT,
            "--model", self.model,
        ]

    def _reply(self, proc) -> str:
        # On failure the CLI still prints a JSON envelope whose "result" says what went wrong
        # (for example "Not logged in"), so the envelope is read before the exit code is judged.
        try:
            envelope = json.loads(proc.stdout)
        except ValueError:
            envelope = None
        if isinstance(envelope, dict) and envelope.get("is_error"):
            raise ModelError(str(envelope.get("result") or envelope.get("subtype") or "error"))
        if proc.returncode != 0:
            raise ModelError(f"claude exited with status {proc.returncode}")
        if not isinstance(envelope, dict) or not isinstance(envelope.get("result"), str):
            raise ModelError("claude returned no result")
        return envelope["result"]


class CodexCli(_CliClient):
    executable = "codex"

    def _argv(self, cwd: Path) -> list[str]:
        return [
            self.executable, "exec", "--json",
            "-m", self.model,
            "--sandbox", "read-only",
            "-c", "approval_policy=never",
            "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check",
        ]

    def _reply(self, proc) -> str:
        if proc.returncode != 0:
            raise ModelError(f"codex exited with status {proc.returncode}")
        reply = None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue  # codex can print a stray non-JSON line
            item = event.get("item") if isinstance(event, dict) else None
            if (
                isinstance(item, dict)
                and event.get("type") == "item.completed"
                and item.get("type") == "agent_message"
            ):
                reply = item.get("text")
        if not isinstance(reply, str):
            raise ModelError("codex returned no agent message")
        return reply
