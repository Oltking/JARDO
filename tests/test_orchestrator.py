from datetime import datetime, timedelta, timezone

from core.orchestrator import Orchestrator
from core.schema import Owner, Policy, Task


async def _owner(session) -> Owner:
    owner = Owner(name="Orch", pronoun_style="sir", email="orch@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.flush()
    return owner


class _Clock:
    def __init__(self):
        self.t = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


async def test_happy_path_runs_and_completes(session):
    owner = await _owner(session)
    orch = Orchestrator({"chat": lambda task, s: _echo(task)})
    task = await orch.enqueue(session, owner.id, "chat", "say hello")
    await orch.run_task(session, task)
    assert task.state == "done"
    assert task.result == "echo: say hello"
    assert task.attempts == 1


async def _echo(task: Task) -> str:
    return f"echo: {task.goal}"


async def test_retry_with_backoff_then_success(session):
    owner = await _owner(session)
    clock = _Clock()
    calls = {"n": 0}

    async def flaky(task, s):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return "ok"

    orch = Orchestrator({"chat": flaky}, clock=clock)
    task = await orch.enqueue(session, owner.id, "chat", "do it")

    await orch.run_task(session, task)               # attempt 1 fails → backoff
    assert task.state == "pending" and task.attempts == 1
    assert task.next_run_at > clock()                # scheduled into the future

    # not yet due
    assert await orch.run_due(session) == []
    clock.advance(10)
    ran = await orch.run_due(session)                # attempt 2 succeeds
    assert len(ran) == 1 and ran[0].state == "done" and ran[0].result == "ok"


async def test_exhausts_attempts_then_fails(session):
    owner = await _owner(session)
    clock = _Clock()

    async def always_fail(task, s):
        raise RuntimeError("nope")

    orch = Orchestrator({"chat": always_fail}, clock=clock)
    task = await orch.enqueue(session, owner.id, "chat", "impossible", max_attempts=2)

    await orch.run_task(session, task)
    assert task.state == "pending"
    clock.advance(60)
    await orch.run_due(session)
    assert task.state == "failed"
    assert task.attempts == 2
    assert "nope" in task.error


async def test_verify_first_blocks_denied_action_before_execution(session):
    owner = await _owner(session)
    executed = {"ran": False}

    async def should_not_run(task, s):
        executed["ran"] = True
        return "executed"

    orch = Orchestrator({"action": should_not_run})
    task = await orch.enqueue(session, owner.id, "action", "free disk space",
                              spec={"action_type": "shell.run", "target": "rm -rf ~/"})
    await orch.run_task(session, task)
    assert task.state == "failed"
    assert "denied" in task.error
    assert executed["ran"] is False  # never executed — verify-first stopped it


async def test_policy_allowed_action_executes(session):
    owner = await _owner(session)
    session.add(Policy(action_type="shell.run", target_pattern=r"ls .*",
                       tier="always-allow"))
    await session.flush()

    async def run_action(task, s):
        return "listed"

    orch = Orchestrator({"action": run_action})
    task = await orch.enqueue(session, owner.id, "action", "list files with ls",
                              spec={"action_type": "shell.run", "target": "ls -la"})
    await orch.run_task(session, task)
    assert task.state == "done" and task.result == "listed"


async def test_resume_stuck_requeues_inflight_tasks(session):
    owner = await _owner(session)
    orch = Orchestrator({"chat": lambda t, s: _echo(t)})
    task = await orch.enqueue(session, owner.id, "chat", "interrupted")
    task.state = "executing"  # simulate a crash mid-run
    await session.flush()

    resumed = await orch.resume_stuck(session)
    assert resumed == 1
    assert task.state == "pending"
    assert task.checkpoint.get("resumed") is True


async def test_run_due_processes_one_at_a_time(session):
    owner = await _owner(session)
    order = []

    async def track(task, s):
        order.append(task.goal)
        return "ok"

    orch = Orchestrator({"chat": track})
    for i in range(3):
        await orch.enqueue(session, owner.id, "chat", f"task {i}")

    ran = await orch.run_due(session, limit=1)
    assert len(ran) == 1  # strictly one per call
    assert len(order) == 1
