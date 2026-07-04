"""Tests for the Jardo MCP server tools (spec §4.3).

We exercise the session-injected `*_impl` coroutines directly with the pytest
`session` fixture (conftest.py) — no live stdio transport required — mirroring
the style of tests/test_supervisor.py and tests/test_sentinel.py.
"""

from sqlalchemy import select

from core.mcp_server.server import (
    decide_approval_impl,
    list_pending_approvals_impl,
    request_action_approval_impl,
)
from core.schema import Approval, Policy


async def test_dangerous_action_is_denied(session):
    result = await request_action_approval_impl(
        session, "claude-code", "shell.run", "rm -rf ~/", "free up disk space")
    assert result["verdict"] == "deny"
    assert result["severity"] == "critical"
    assert result["actor"] == "claude-code"
    assert any(f["check"] == "dangerous-pattern" for f in result["findings"])


async def test_policy_approved_action_is_approved(session):
    session.add(Policy(action_type="shell.run", target_pattern=r"ls .*",
                       tier="always-allow"))
    await session.flush()
    result = await request_action_approval_impl(
        session, "claude-code", "shell.run", "ls -la", "list the project files with ls")
    assert result["verdict"] == "approve"
    assert result["tier"] == "always-allow"


async def test_unknown_action_escalates_and_creates_pending_approval(session):
    result = await request_action_approval_impl(
        session, "claude-code", "app.open", "open Safari", "open the safari browser")
    assert result["verdict"] == "escalate-to-owner"

    pending = await list_pending_approvals_impl(session)
    assert len(pending) == 1
    assert pending[0]["action_type"] == "app.open"
    assert pending[0]["status"] == "pending"


async def test_decide_approval_flips_pending_row(session):
    await request_action_approval_impl(
        session, "claude-code", "app.open", "open Notes", "open the notes app")
    pending = await list_pending_approvals_impl(session)
    approval_id = pending[0]["id"]

    decision = await decide_approval_impl(session, approval_id, approve=True)
    assert decision["ok"] is True
    assert decision["approval"]["status"] == "approved"

    # No longer pending, and the row really changed in the DB.
    assert await list_pending_approvals_impl(session) == []
    row = (await session.execute(
        select(Approval).where(Approval.status == "approved")
    )).scalars().one()
    assert str(row.id) == approval_id


async def test_decide_approval_rejects_bad_id(session):
    result = await decide_approval_impl(session, "not-a-uuid", approve=True)
    assert result["ok"] is False
    assert "invalid" in result["error"]
