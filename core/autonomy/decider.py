"""Autonomous decision (spec §4.3 necessity + §6 safety, §8 acting-for-owner).

When Jardo works unattended, it decides for the owner rather than queuing: it
checks a command's SAFETY (Sentinel dangerous-pattern scan) and its PURPOSE
(alignment with the owner's objective), and either runs it or refuses it. It
never waits. Safety is conservative for unattended work: anything MEDIUM or
above (sudo, destructive, credential access, pipe-to-shell) is refused outright,
regardless of alignment — the owner can do those when present (§6: owner's
security first).
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.sentinel.checks import scan_dangerous_patterns, scan_secrets
from core.sentinel.models import ActionRequest, Severity

_BLOCK_AT_OR_ABOVE = (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)


@dataclass
class Decision:
    approve: bool
    reason: str
    severity: str


async def autonomous_decision(session: AsyncSession, command: str, objective: str,
                              chat_fn=None) -> Decision:
    request = ActionRequest("jardo", "shell.run", command, objective or "")

    # 1. Safety — refuse anything risky for unattended execution.
    findings = scan_dangerous_patterns(request) + scan_secrets(request)
    blocking = [f for f in findings if f.severity in _BLOCK_AT_OR_ABOVE]
    if blocking:
        worst = max(blocking, key=lambda f: _BLOCK_AT_OR_ABOVE.index(f.severity))
        return Decision(False, f"unsafe to run unattended: {worst.message}",
                        str(worst.severity))

    # 2. Purpose — must serve the owner's objective (if one is set).
    if objective and objective.strip():
        from core.supervision import judge_alignment
        alignment = await judge_alignment(
            objective, f"run in terminal: {command}", chat_fn=chat_fn)
        if not alignment.aligned:
            return Decision(False, f"off-task for '{objective[:60]}': {alignment.reason}",
                            "low")

    return Decision(True, "safe and on-task — acting on your behalf", "low")
