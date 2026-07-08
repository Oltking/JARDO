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
                              chat_fn=None, totp_code: str | None = None,
                              conservative: bool = False) -> Decision:
    request = ActionRequest("jardo", "shell.run", command, objective or "")

    # 1. Safety — refuse anything risky for unattended execution.
    findings = scan_dangerous_patterns(request) + scan_secrets(request)
    blocking = [f for f in findings if f.severity in _BLOCK_AT_OR_ABOVE]
    if blocking:
        worst = max(blocking, key=lambda f: _BLOCK_AT_OR_ABOVE.index(f.severity))
        # Truly forbidden actions (e.g. active scanning of third parties, illegal
        # without authorization — SECURITY.md rule 2) are never permitted.
        if any("forbidden" in f.message for f in blocking):
            return Decision(False, f"forbidden and never permitted: {worst.message}",
                            str(worst.severity))
        # Otherwise the owner can authorize a risky action with a fresh TOTP code
        # (spec §4.1 — TOTP is the gate for destructive/high-privilege actions).
        from core import totp
        if totp_code and totp.verify(totp_code):
            return Decision(True, f"owner-authorized via TOTP despite risk "
                            f"({worst.message})", str(worst.severity))
        suffix = (" — a TOTP code from you would authorize it"
                  if totp.is_enrolled() else "")
        return Decision(False, f"unsafe to run unattended: {worst.message}{suffix}",
                        str(worst.severity))

    # 1b. Conservative posture for unattended auto-approval (audit #1): a denylist
    # can't catch every destructive command, so only auto-approve commands we
    # positively recognize as safe. Everything else is declined (never run) — the
    # owner can run it themselves.
    if conservative:
        from core import appsettings
        from core.sentinel.checks import is_recognizably_safe
        learned = frozenset(appsettings.get("allowed_programs", []) or [])
        if not is_recognizably_safe(command, learned):
            return Decision(False, "not a recognizably-safe command — declined for "
                            "safety while acting unattended; run it yourself, or add "
                            "it with 'jardo allow'", "low")

    # 2. Purpose — must serve the owner's objective (if one is set).
    if objective and objective.strip():
        from core.supervision import judge_alignment
        alignment = await judge_alignment(
            objective, f"run in terminal: {command}", chat_fn=chat_fn)
        if not alignment.aligned:
            return Decision(False, f"off-task for '{objective[:60]}': {alignment.reason}",
                            "low")

    return Decision(True, "safe and on-task — acting on your behalf", "low")
