"""Orchestrator (spec §4.2): autonomous, one-task-at-a-time durable executor.

Each task runs a **verify → route → execute → verify → log** loop:
  1. VERIFY FIRST ("verify anything first", §4.2): restate the goal, check
     assumptions, and for action tasks run the Security Sentinel BEFORE doing
     anything. A denied action fails fast without execution.
  2. EXECUTE via a pluggable executor registered per task kind. Executors are
     injected (real ones dispatch to models / gated actions; tests use fakes),
     so the durability machinery is testable without side effects.
  3. On failure: retry with exponential backoff up to max_attempts, checkpointing
     state to Postgres after every transition so a crash mid-run resumes cleanly.

Designed for 24h+ unattended runs (§4.2): strictly one task at a time, never
blocks on the owner when a documented policy covers the decision, resumes after
a crash via resume_stuck().
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.memory import MemoryStore
from core.schema import Task
from core.sentinel.broker import Sentinel
from core.sentinel.models import ActionRequest, Verdict

logger = logging.getLogger("jardo.orchestrator")

# executor(task, session) -> result string; may raise to trigger retry/backoff.
Executor = Callable[[Task, AsyncSession], Awaitable[str]]

_BASE_BACKOFF = timedelta(seconds=2)
_MAX_BACKOFF = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class VerifyResult:
    ok: bool
    reason: str


class Orchestrator:
    def __init__(self, executors: dict[str, Executor], clock: Callable[[], datetime] = _now):
        self._executors = executors
        self._clock = clock

    # -- enqueue ----------------------------------------------------------
    async def enqueue(self, session: AsyncSession, owner_id, kind: str, goal: str,
                      spec: dict | None = None, max_attempts: int = 3) -> Task:
        task = Task(owner_id=owner_id, kind=kind, goal=goal, spec=spec or {},
                    state="pending", max_attempts=max_attempts, next_run_at=self._clock())
        session.add(task)
        await session.flush()
        await MemoryStore(session).audit("orchestrator", "task.enqueued",
                                         {"task_id": str(task.id), "kind": kind})
        return task

    # -- verification-first (§4.2) ---------------------------------------
    async def verify(self, task: Task, session: AsyncSession) -> VerifyResult:
        if not task.goal.strip():
            return VerifyResult(False, "empty goal")
        if task.kind not in self._executors:
            return VerifyResult(False, f"no executor for kind '{task.kind}'")
        # Action + coding tasks pass the Sentinel before execution — no direct
        # paths (§0.3). Coding tasks additionally gate interactive prompts at
        # run time via SupervisedAgent, so this reviews the top-level command.
        if task.kind in ("action", "coding"):
            request = ActionRequest(
                actor="orchestrator",
                action_type=task.spec.get("action_type", "shell.run"),
                target=task.spec.get("target") or task.spec.get("command", ""),
                stated_goal=task.goal,
            )
            review = await Sentinel(session).review(request)
            if review.verdict == Verdict.DENY:
                return VerifyResult(False, f"sentinel denied: {review.severity}")
            if review.verdict in (Verdict.ESCALATE, Verdict.APPROVE_WITH_EDITS):
                # Not auto-approved by policy → do not act autonomously (§8 rule).
                return VerifyResult(False, f"needs owner approval: {review.verdict}")
        return VerifyResult(True, "verified")

    # -- run one task -----------------------------------------------------
    async def run_task(self, session: AsyncSession, task: Task) -> Task:
        store = MemoryStore(session)
        task.state = "verifying"
        task.attempts += 1
        task.checkpoint = {"phase": "verify", "attempt": task.attempts}
        await session.flush()

        verification = await self.verify(task, session)
        if not verification.ok:
            return await self._fail(session, store, task, verification.reason,
                                    retriable=False)

        task.state = "executing"
        task.checkpoint = {"phase": "execute", "attempt": task.attempts}
        await session.flush()
        try:
            result = await self._executors[task.kind](task, session)
        except Exception as exc:  # noqa: BLE001 — any executor failure is retriable
            return await self._fail(session, store, task, repr(exc), retriable=True)

        task.state = "done"
        task.result = result
        task.error = None
        task.checkpoint = {"phase": "done", "attempt": task.attempts}
        await session.flush()
        await store.audit("orchestrator", "task.done",
                          {"task_id": str(task.id), "attempts": task.attempts})
        return task

    async def _fail(self, session: AsyncSession, store: MemoryStore, task: Task,
                    reason: str, retriable: bool) -> Task:
        task.error = reason
        if retriable and task.attempts < task.max_attempts:
            backoff = min(_BASE_BACKOFF * (2 ** (task.attempts - 1)), _MAX_BACKOFF)
            task.state = "pending"
            task.next_run_at = self._clock() + backoff
            task.checkpoint = {"phase": "backoff", "attempt": task.attempts,
                               "retry_in_s": backoff.total_seconds()}
            await store.audit("orchestrator", "task.retry",
                              {"task_id": str(task.id), "attempt": task.attempts,
                               "reason": reason})
        else:
            task.state = "failed"
            task.checkpoint = {"phase": "failed", "attempt": task.attempts}
            await store.audit("orchestrator", "task.failed",
                              {"task_id": str(task.id), "reason": reason})
        await session.flush()
        return task

    # -- driver: pick and run due tasks, strictly one at a time ----------
    async def run_due(self, session: AsyncSession, limit: int = 1) -> list[Task]:
        done = []
        for _ in range(limit):
            task = (await session.execute(
                select(Task).where(Task.state == "pending",
                                   Task.next_run_at <= self._clock())
                .order_by(Task.next_run_at).limit(1)
            )).scalar_one_or_none()
            if task is None:
                break
            done.append(await self.run_task(session, task))
        return done

    async def resume_stuck(self, session: AsyncSession) -> int:
        """Crash recovery (§4.2): tasks left mid-flight get requeued."""
        stuck = (await session.execute(
            select(Task).where(Task.state.in_(("verifying", "executing")))
        )).scalars().all()
        for task in stuck:
            task.state = "pending"
            task.next_run_at = self._clock()
            task.checkpoint = {**task.checkpoint, "resumed": True}
        if stuck:
            await MemoryStore(session).audit("orchestrator", "tasks.resumed",
                                             {"count": len(stuck)})
        await session.flush()
        return len(stuck)


async def run_forever(orchestrator: Orchestrator, session_factory,
                      poll_interval: float = 1.0) -> None:  # pragma: no cover
    """Long-running driver loop for `jardo run` (24h unattended, §4.2)."""
    async with session_factory() as session:
        await orchestrator.resume_stuck(session)
        await session.commit()
    while True:
        async with session_factory() as session:
            ran = await orchestrator.run_due(session, limit=1)
            await session.commit()
        await asyncio.sleep(0.0 if ran else poll_interval)
