"""PTY terminal control (spec §7.2): JARVIS owns a real PTY.

It reads command output and types commands programmatically — it does NOT
blind-inject keystrokes into whatever terminal happens to be focused (§7.2).
This is also how it answers input/permission prompts from CLI coding agents.

Every command is Sentinel-gated before it runs (§7.3): the terminal takes a
`review_fn` that must return an approving verdict, so there is no ungated
execution path (spec §0.3). The default factory wires in the real Sentinel.

Source: docs/vendor/computer-use/pexpect-overview.md, pexpect-api.md
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pexpect

from core.sentinel.models import ActionRequest, Verdict

# review_fn(ActionRequest) -> Verdict
ReviewFn = Callable[[ActionRequest], Awaitable[Verdict]]


class TerminalDenied(RuntimeError):
    """Raised when the Sentinel does not approve a command."""


@dataclass
class CommandResult:
    command: str
    output: str
    exit_status: int | None


class PtyTerminal:
    """A single long-lived shell session driven over a real PTY."""

    def __init__(self, review_fn: ReviewFn, shell: str = "/bin/bash",
                 actor: str = "jarvis", timeout: float = 30.0):
        self._review_fn = review_fn
        self._actor = actor
        self._timeout = timeout
        self._prompt = "JARVIS_PTY_PROMPT>> "
        self._child = pexpect.spawn(shell, encoding="utf-8", echo=False,
                                    timeout=timeout)
        # Deterministic prompt so we can reliably delimit command output.
        self._child.sendline(f"PS1='{self._prompt}'; PS2=''")
        self._child.expect_exact(self._prompt)

    async def run(self, command: str, stated_goal: str) -> CommandResult:
        request = ActionRequest(actor=self._actor, action_type="shell.run",
                                target=command, stated_goal=stated_goal)
        verdict = await self._review_fn(request)
        if verdict not in (Verdict.APPROVE, Verdict.APPROVE_WITH_EDITS):
            raise TerminalDenied(f"sentinel verdict {verdict} for: {command}")

        self._child.sendline(command)
        self._child.expect_exact(self._prompt)
        output = self._child.before.replace(command, "", 1).strip("\r\n")

        # Capture exit status of the command just run.
        self._child.sendline("echo EXIT:$?")
        self._child.expect_exact(self._prompt)
        status_line = self._child.before
        exit_status = None
        for token in status_line.split():
            if token.startswith("EXIT:"):
                try:
                    exit_status = int(token.split(":", 1)[1])
                except ValueError:
                    exit_status = None
        return CommandResult(command=command, output=output, exit_status=exit_status)

    def close(self) -> None:
        if self._child.isalive():
            self._child.sendline("exit")
            self._child.close(force=True)


def make_sentinel_review_fn(session) -> ReviewFn:
    """Wire a PtyTerminal to the real Security Sentinel."""
    from core.sentinel.broker import Sentinel

    async def review(request: ActionRequest) -> Verdict:
        return (await Sentinel(session).review(request)).verdict

    return review
