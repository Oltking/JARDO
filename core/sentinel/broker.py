"""Security Sentinel pipeline + Permission Broker (spec §6).

Flow per action: static checks → necessity test → severity roll-up → policy tier
→ verdict. Everything lands in the append-only audit log; escalations persist as
pending approvals (CLI approve/deny now, desktop UI at Phase 5).

Tier resolution (§6.5): owner policies are (action_type, target_pattern) → tier.
Default when no policy matches: ALWAYS_ASK — deny-by-default posture.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.memory import MemoryStore
from core.schema import Approval, Policy
from core.sentinel.checks import (
    check_transport,
    necessity_test,
    scan_dangerous_patterns,
    scan_secrets,
)
from core.sentinel.models import (
    ActionRequest,
    ActionReview,
    Finding,
    Severity,
    Tier,
    Verdict,
)

_SEVERITY_ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


def _max_severity(findings: list[Finding]) -> Severity:
    if not findings:
        return Severity.LOW
    return max((f.severity for f in findings), key=_SEVERITY_ORDER.index)


async def resolve_tier(session: AsyncSession, request: ActionRequest) -> Tier:
    rows = (await session.execute(
        select(Policy).where(Policy.action_type == request.action_type)
    )).scalars().all()
    for policy in rows:
        if re.fullmatch(policy.target_pattern, request.target):
            return Tier(policy.tier)
    return Tier.ALWAYS_ASK  # deny-by-default


class Sentinel:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.store = MemoryStore(session)

    async def review(self, request: ActionRequest) -> ActionReview:
        findings = (
            scan_dangerous_patterns(request)
            + scan_secrets(request)
            + check_transport(request)
        )
        necessary, necessity_reason = necessity_test(request)
        if not necessary:
            findings.append(Finding("necessity", Severity.MEDIUM,
                                    f"fails necessity test: {necessity_reason}"))
        severity = _max_severity(findings)
        tier = await resolve_tier(self.session, request)

        # Verdict logic (§6): CRITICAL findings are denied outright — no tier
        # can whitelist a forbidden pattern. HIGH escalates to the owner even on
        # always-allow. Otherwise the tier decides.
        if severity == Severity.CRITICAL:
            verdict = Verdict.DENY
        elif severity == Severity.HIGH:
            verdict = Verdict.ESCALATE
        elif tier == Tier.ALWAYS_ALLOW:
            verdict = Verdict.APPROVE if necessary else Verdict.ESCALATE
        elif tier == Tier.ASK_ONCE:
            verdict = await self._ask_once_verdict(request)
        else:
            verdict = Verdict.ESCALATE

        review = ActionReview(
            request=request,
            expected_outcome=request.stated_goal,
            findings=findings,
            necessary=necessary,
            necessity_reason=necessity_reason,
            verdict=verdict,
            severity=severity,
            tier=tier,
        )
        await self._record(review)
        return review

    async def _ask_once_verdict(self, request: ActionRequest) -> Verdict:
        """ask-once (§6.5): approved once by the owner → auto-approve same
        action_type+target afterwards."""
        prior = (await self.session.execute(
            select(Approval).where(
                Approval.action_type == request.action_type,
                Approval.target == request.target,
                Approval.status == "approved",
            )
        )).scalars().first()
        return Verdict.APPROVE if prior else Verdict.ESCALATE

    async def _record(self, review: ActionReview) -> None:
        from core.sentinel.checks import redact
        detail = {
            "actor": review.request.actor,
            "action_type": review.request.action_type,
            "target": redact(review.request.target[:500]),
            "verdict": review.verdict,
            "severity": review.severity,
            "tier": review.tier,
            "findings": [f"{f.check}:{f.severity}:{f.message}" for f in review.findings],
            "necessity": review.necessity_reason,
        }
        await self.store.audit("sentinel", "action.review", detail)
        # §6.6: severity ≥ medium feeds the hourly report immediately (Phase 8
        # reads these events; recording now keeps the contract).
        if review.severity in (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
            await self.store.audit("sentinel", "security.event", detail)
        if review.verdict == Verdict.ESCALATE:
            self.session.add(Approval(
                actor=review.request.actor,
                action_type=review.request.action_type,
                target=review.request.target,
                stated_goal=review.request.stated_goal,
                severity=review.severity,
                status="pending",
            ))
            await self.session.flush()


async def decide_pending(session: AsyncSession, approval_id: uuid.UUID,
                         approve: bool) -> Approval | None:
    approval = await session.get(Approval, approval_id)
    if approval is None or approval.status != "pending":
        return None
    approval.status = "approved" if approve else "denied"
    store = MemoryStore(session)
    await store.audit("owner", "approval.decided",
                      {"approval_id": str(approval_id), "status": approval.status})
    await session.flush()
    return approval
