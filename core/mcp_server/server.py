"""Jardo MCP server (spec §4.3): the Agent Supervisor exposed as an MCP server.

Built with the official Python SDK's FastMCP over stdio transport, per
  docs/vendor/mcp/quickstart-build-server.md  (Python: `from mcp.server.fastmcp
  import FastMCP`, `mcp.run(transport="stdio")`)
  docs/vendor/mcp/spec-server-tools.md         (tools/list + tools/call contract)

Design:
- Each MCP tool opens its OWN DB session via core.db.SessionFactory and commits,
  so callers get a clean, isolated transaction per request.
- The heavy lifting is done by module-level `*_impl` coroutines that take an
  explicit session. The `@mcp.tool()` wrappers are thin session-management shells
  around them. Tests exercise the `_impl` functions directly with the pytest
  `session` fixture (no live stdio transport needed).
- All supervision reuses core.sentinel.broker.Sentinel / decide_pending — the
  Sentinel is NOT reimplemented here (spec §4.3).

stdio logging rule (quickstart-build-server.md §"Logging in MCP Servers"): never
write to stdout — it corrupts the JSON-RPC stream. We log to stderr only.
"""

import logging
import sys
import uuid

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import SessionFactory
from core.schema import Approval
from core.sentinel.broker import Sentinel, decide_pending
from core.sentinel.models import ActionRequest, ActionReview

logger = logging.getLogger("jardo.mcp")

mcp = FastMCP("jardo-supervisor")


# ---------- serialization -------------------------------------------------

def review_to_dict(review: ActionReview) -> dict:
    """Flatten an ActionReview into the structured payload agents receive
    (spec §4.3: verbatim action, expected outcome, risks, necessity, verdict)."""
    return {
        "actor": review.request.actor,
        "action_type": review.request.action_type,
        "target": review.request.target,
        "stated_goal": review.request.stated_goal,
        "expected_outcome": review.expected_outcome,
        "verdict": str(review.verdict),
        "severity": str(review.severity),
        "tier": str(review.tier),
        "necessary": review.necessary,
        "necessity_reason": review.necessity_reason,
        "findings": [
            {"check": f.check, "severity": str(f.severity), "message": f.message}
            for f in review.findings
        ],
    }


def approval_to_dict(approval: Approval) -> dict:
    return {
        "id": str(approval.id),
        "actor": approval.actor,
        "action_type": approval.action_type,
        "target": approval.target,
        "stated_goal": approval.stated_goal,
        "severity": approval.severity,
        "status": approval.status,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
    }


# ---------- implementations (session-injected, unit-testable) -------------

async def request_action_approval_impl(
    session: AsyncSession, actor: str, action_type: str, target: str, stated_goal: str
) -> dict:
    request = ActionRequest(
        actor=actor, action_type=action_type, target=target, stated_goal=stated_goal
    )
    review = await Sentinel(session).review(request)
    return review_to_dict(review)


async def list_pending_approvals_impl(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(
        select(Approval).where(Approval.status == "pending")
        .order_by(Approval.created_at)
    )).scalars().all()
    return [approval_to_dict(row) for row in rows]


async def decide_approval_impl(
    session: AsyncSession, approval_id: str, approve: bool
) -> dict:
    try:
        parsed = uuid.UUID(approval_id)
    except (ValueError, AttributeError):
        return {"ok": False, "error": f"invalid approval_id: {approval_id!r}"}
    approval = await decide_pending(session, parsed, approve)
    if approval is None:
        return {"ok": False, "error": "not found or already decided",
                "approval_id": approval_id}
    return {"ok": True, "approval": approval_to_dict(approval)}


# ---------- MCP tools (own session per call, then commit) -----------------

@mcp.tool()
async def request_action_approval(
    actor: str, action_type: str, target: str, stated_goal: str
) -> dict:
    """Run a proposed action through Jardo's Security Sentinel and return the
    structured Action Review (spec §4.3).

    Args:
        actor: who wants to act (e.g. "claude-code", "cursor", an agent id).
        action_type: category, e.g. "shell.run", "net.fetch", "fs.write", "app.open".
        target: the concrete command line, URL, path, or app name.
        stated_goal: what the actor claims this achieves (drives the necessity test).

    Returns a dict with verdict (approve | approve-with-edits | deny |
    escalate-to-owner), severity, tier, necessity, and findings. Escalated
    actions create a pending Approval the owner resolves via decide_approval.
    """
    async with SessionFactory() as session:
        result = await request_action_approval_impl(
            session, actor, action_type, target, stated_goal
        )
        await session.commit()
        return result


@mcp.tool()
async def list_pending_approvals() -> list:
    """List actions that escalated to the owner and are still awaiting a decision
    (spec §6.5 Permission Broker). Returns a list of pending Approval rows."""
    async with SessionFactory() as session:
        return await list_pending_approvals_impl(session)


@mcp.tool()
async def decide_approval(approval_id: str, approve: bool) -> dict:
    """Owner-tier resolution of an escalation (spec §6.5): approve or deny a
    pending Approval by id. Wraps core.sentinel.broker.decide_pending.

    Args:
        approval_id: the pending Approval's UUID (as returned by list_pending_approvals).
        approve: True to approve, False to deny.
    """
    async with SessionFactory() as session:
        result = await decide_approval_impl(session, approval_id, approve)
        await session.commit()
        return result


def main() -> None:
    """Start the Jardo MCP server over stdio (the standard MCP transport).

    Per quickstart-build-server.md, stdio servers must keep stdout clean for the
    JSON-RPC stream — logging is pinned to stderr here.
    """
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logger.info("Starting Jardo MCP server (jardo-supervisor) on stdio")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
