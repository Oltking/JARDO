"""Agent Supervisor (spec §4.3): maps external agents' proposed actions into
Sentinel reviews and answers their permission questions per owner policy.

Claude Code integration contract (docs/vendor/claude-code/hooks-reference.md):
  PreToolUse hook stdin: {"tool_name", "tool_input", "tool_use_id", ...}
  Response: {"hookSpecificOutput": {"hookEventName": "PreToolUse",
             "permissionDecision": "allow"|"deny"|"ask",
             "permissionDecisionReason": "..."}}
  Exit 0 / no output = no decision (normal permission flow continues).
Verdict mapping: approve→allow, deny→deny, everything else→ask. Jardo never
silently widens permissions: "ask" hands the decision back to the owner.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from core.sentinel.broker import Sentinel
from core.sentinel.models import ActionRequest, ActionReview, Verdict

# Claude Code tool → (action_type, field holding the target)
# tool_input schemas: docs/vendor/claude-code/hooks-reference.md §PreToolUse input
_TOOL_MAP = {
    "Bash": ("shell.run", "command"),
    "Write": ("fs.write", "file_path"),
    "Edit": ("fs.write", "file_path"),
    "NotebookEdit": ("fs.write", "notebook_path"),
    "Read": ("fs.read", "file_path"),
    "Glob": ("fs.read", "pattern"),
    "Grep": ("fs.read", "pattern"),
    "WebFetch": ("net.fetch", "url"),
    "WebSearch": ("net.fetch", "query"),
}

_DECISION = {
    Verdict.APPROVE: "allow",
    Verdict.DENY: "deny",
    Verdict.APPROVE_WITH_EDITS: "ask",
    Verdict.ESCALATE: "ask",
}


def map_tool_call(actor: str, tool_name: str, tool_input: dict,
                  stated_goal: str = "") -> ActionRequest:
    action_type, target_field = _TOOL_MAP.get(tool_name, (f"tool.{tool_name}", ""))
    target = str(tool_input.get(target_field, "")) if target_field else str(tool_input)[:500]
    goal = stated_goal or str(tool_input.get("description", "")) or f"use {tool_name}"
    return ActionRequest(actor=actor, action_type=action_type, target=target,
                         stated_goal=goal, payload=tool_input)


def review_to_decision(review: ActionReview) -> dict:
    reasons = [f"{f.check}: {f.message}" for f in review.findings]
    return {
        "permissionDecision": _DECISION[review.verdict],
        "permissionDecisionReason": (
            f"Jardo sentinel: {review.verdict} (severity={review.severity}, "
            f"tier={review.tier})" + (f" — {'; '.join(reasons)}" if reasons else "")
        ),
    }


async def supervise_tool_call(session: AsyncSession, actor: str, tool_name: str,
                              tool_input: dict, stated_goal: str = "",
                              align_chat_fn=None) -> dict:
    """Supervise one agent tool call. If an oversight objective is active
    (core.supervision), the action is judged against the OWNER's objective, not
    the agent's own claim — and an off-task action is escalated even if the
    Sentinel would otherwise allow it (spec §4.3 necessity test)."""
    from core.supervision import get_active, judge_alignment

    session_objective = await get_active(session)
    goal = session_objective.objective if session_objective else stated_goal
    request = map_tool_call(actor, tool_name, tool_input, goal)
    review = await Sentinel(session).review(request)

    if session_objective and review.verdict == Verdict.APPROVE:
        # Objective-gating: only ever tightens an approve → escalate; never loosens.
        alignment = await judge_alignment(
            session_objective.objective, f"{request.action_type}: {request.target}",
            chat_fn=align_chat_fn)
        if not alignment.aligned:
            decision = {
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    f"Jardo: off-task for your objective "
                    f"('{session_objective.objective[:80]}') — {alignment.reason}. "
                    "Escalated for your confirmation."),
            }
            from core.memory import MemoryStore
            await MemoryStore(session).audit("supervisor", "action.off_task", {
                "objective": session_objective.objective[:200],
                "action": request.target[:200], "judged_by": alignment.judged_by})
            return decision
    return review_to_decision(review)
