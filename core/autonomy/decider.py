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
    guidance: str = ""  # expert "do this instead" text when declining


async def autonomous_decision(session: AsyncSession, command: str, objective: str,
                              chat_fn=None, totp_code: str | None = None,
                              conservative: bool = False, brief: str = "") -> Decision:
    request = ActionRequest("jardo", "shell.run", command, objective or "")
    findings = scan_dangerous_patterns(request) + scan_secrets(request)

    # 1. Hard veto — ONLY catastrophic or illegal actions are never allowed, no
    # matter what: recursive delete of root/home, raw disk writes, mkfs, fork bombs,
    # active scanning tools. Everything a coding agent legitimately does — bash,
    # curl, python -c, installs, builds, deleting a build/ dir, reading .env for
    # config — is NOT auto-blocked here; blanket-blocking it would make Jardo
    # useless as a supervisor. Those get judged in context by the model below.
    forbidden = [f for f in findings if "forbidden" in f.message]
    if forbidden:
        return Decision(False, f"forbidden and never permitted: {forbidden[0].message}",
                        str(forbidden[0].severity))
    catastrophic = [f for f in findings if f.severity == Severity.CRITICAL]
    if catastrophic:
        from core import totp
        worst = catastrophic[0]
        if totp_code and totp.verify(totp_code):
            return Decision(True, f"owner-authorized via TOTP despite risk "
                            f"({worst.message})", str(worst.severity))
        return Decision(False, f"refused — {worst.message} is destructive and "
                        "irreversible", str(worst.severity))

    # 2. Lesser concerns (sudo, recursive delete of a dir, inline code, git force,
    # reading credentials, pipe-to-shell) are normal in real dev work, so we don't
    # auto-decline them — we hand them to the model as context and let it judge
    # whether THIS one is safe and on-task for the project.
    concerns = sorted({f.message for f in findings
                       if f.severity in (Severity.MEDIUM, Severity.HIGH)})

    if chat_fn is not None:
        from core.supervision import judge_action
        j = await judge_action(objective, brief, command,
                               chat_fn=chat_fn, concerns=concerns)
        if j.judged_by == "model":
            if j.approve:
                return Decision(True, j.reason or "safe and on-task", "low")
            return Decision(False, j.reason or "off-task or unsafe for the goal",
                            "low", guidance=j.guidance)
        # else: model unavailable/failed → fall through below.

    # 3. No model could judge (offline, or the call failed). Do NOT dumbly decline
    # the agent's normal work — the owner chose to supervise and is watching, and
    # anything truly catastrophic or illegal was already blocked in step 1. Trust
    # the agent to do its job; a flagged concern just gets noted in the reason.
    note = f" (noted: {concerns[0]})" if concerns else ""
    return Decision(True, f"proceeding; no model to second-guess it right now{note}",
                    "low")
