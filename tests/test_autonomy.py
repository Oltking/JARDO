"""Autonomous decision: safety + purpose, acting for the owner (no waiting)."""

from core.autonomy.decider import autonomous_decision
from core.schema import Owner


async def _owner(session) -> Owner:
    owner = Owner(name="O", pronoun_style="sir", email="o@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.flush()
    return owner


async def test_safe_aligned_command_approved(session):
    await _owner(session)
    d = await autonomous_decision(session, "git status", "check the git status of the repo")
    assert d.approve is True


async def test_critical_command_refused(session):
    d = await autonomous_decision(session, "rm -rf /", "free disk space")
    assert d.approve is False
    assert "unsafe" in d.reason


async def test_medium_severity_refused_when_unattended(session):
    # sudo is MEDIUM — too risky to run unattended even if plausibly on-task
    d = await autonomous_decision(session, "sudo apt install cowsay", "install cowsay with sudo")
    assert d.approve is False


async def test_credential_access_refused(session):
    d = await autonomous_decision(session, "cat ~/.aws/credentials", "read aws credentials")
    assert d.approve is False


async def test_off_task_command_refused(session):
    async def off_task(_prompt):
        return "OFF-TASK"

    # benign command (ls) but the model judges it off-task for the objective
    d = await autonomous_decision(session, "ls ~/Photos", "write the project documentation",
                                  chat_fn=off_task)
    assert d.approve is False
    assert "off-task" in d.reason


async def test_no_objective_only_safety_gates(session):
    # with no objective, a safe command is allowed on safety alone
    d = await autonomous_decision(session, "ls -la", "")
    assert d.approve is True
