"""Autonomous coding tasks through the durable orchestrator: verify-gates the
command, runs it under prompt supervision, checkpoints the result."""

import json
import sys

import pytest

from core.coding_env.executor import build_coding_orchestrator
from core.schema import Owner, Policy

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pty POSIX only")


async def _owner(session) -> Owner:
    owner = Owner(name="Coder", pronoun_style="sir", email="coder@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.flush()
    return owner


async def test_coding_task_blocked_by_verify_when_not_approved(session):
    owner = await _owner(session)
    orch = build_coding_orchestrator()
    task = await orch.enqueue(session, owner.id, "coding", "delete everything",
                              spec={"command": "rm -rf /"})
    await orch.run_task(session, task)
    # verify-first gates the top command: rm -rf / is critical → denied, never runs
    assert task.state == "failed"
    assert "denied" in task.error


async def test_coding_task_runs_and_checkpoints_when_policied(session):
    owner = await _owner(session)
    session.add(Policy(action_type="shell.run", target_pattern=r"echo .*",
                       tier="always-allow"))
    await session.flush()
    orch = build_coding_orchestrator()
    task = await orch.enqueue(session, owner.id, "coding", "print a greeting with echo",
                              spec={"command": "echo hello-from-jardo"})
    await orch.run_task(session, task)
    assert task.state == "done"
    result = json.loads(task.result)
    assert "hello-from-jardo" in result["output_tail"]
    assert task.checkpoint["phase"] == "done"
