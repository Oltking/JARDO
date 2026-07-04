"""Run a coding agent/command under Jardo's prompt supervision (spec §4.3, §7.2).

Jardo spawns the process in a PTY, streams its output, and whenever an
interactive permission prompt appears it evaluates the proposed action through
the Security Sentinel and types the answer per policy — recording every decision
in the audit log. The owner never has to click y/n for policy-covered actions;
anything not covered is declined (safe default) and surfaced for approval.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.coding_env.prompt_responder import decide_answer, detect_prompt
from core.memory import MemoryStore
from core.sentinel.broker import Sentinel
from core.sentinel.models import ActionRequest

logger = logging.getLogger("jardo.supervised_agent")


class SupervisedAgent:
    def __init__(self, session: AsyncSession, actor: str = "supervised-agent",
                 timeout: float = 120.0):
        self._session = session
        self._sentinel = Sentinel(session)
        self._store = MemoryStore(session)
        self._actor = actor
        self._timeout = timeout

    async def _answer(self, match, stated_goal: str) -> tuple[str, str]:
        """Review the prompt's proposed action and return (token, verdict)."""
        request = ActionRequest(
            actor=self._actor, action_type="shell.run",
            target=match.proposed_action or match.prompt_line,
            stated_goal=stated_goal,
        )
        review = await self._sentinel.review(request)
        token = decide_answer(match, review.verdict)
        await self._store.audit("supervised-agent", "prompt.answered", {
            "prompt": match.prompt_line[:200],
            "action": match.proposed_action[:200],
            "verdict": review.verdict,
            "answered": token,
        })
        return token, review.verdict

    async def _effective_goal(self, stated_goal: str) -> str:
        """Prefer the owner's active oversight objective over the caller's goal."""
        from core.supervision import get_active
        active = await get_active(self._session)
        return active.objective if active else stated_goal

    async def run(self, command: str, stated_goal: str, max_prompts: int = 50) -> dict:
        """Spawn `command` in a PTY and auto-answer its permission prompts.
        Returns a transcript + the list of decisions made."""
        import pexpect

        goal = await self._effective_goal(stated_goal)
        child = pexpect.spawn("/bin/bash", ["-lc", command],
                              encoding="utf-8", timeout=self._timeout)
        decisions: list[dict] = []
        buffer = ""
        try:
            while True:
                try:
                    chunk = child.read_nonblocking(size=1024, timeout=self._timeout)
                except pexpect.EOF:
                    break
                except pexpect.TIMEOUT:
                    break
                buffer += chunk
                match = detect_prompt(buffer)
                if match and len(decisions) < max_prompts:
                    token, verdict = await self._answer(match, goal)
                    child.sendline(token)
                    decisions.append({
                        "prompt": match.prompt_line, "action": match.proposed_action,
                        "verdict": str(verdict), "answered": token,
                    })
                    buffer = ""  # consume; avoid re-matching the same prompt
        finally:
            if child.isalive():
                child.close(force=True)
        await self._session.commit()
        return {"decisions": decisions, "transcript_tail": buffer[-2000:]}
