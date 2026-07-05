"""Launch briefing (spec §4.5 morning intent + §4.4 reporting).

On open, Jardo greets the owner, tells them anything that needs attention since
last time (pending approvals, security events, what it did / saved), and asks for
the day's objective — which becomes the supervision goal (core.supervision).

Pure assembly from existing tables + the Reporter rollup, so it is testable.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.memory import MemoryStore
from core.reporter import gather_stats
from core.schema import Approval, SupervisionSession


def _time_greeting(now: datetime, honorific: str, name: str) -> str:
    hour = now.hour
    part = ("Good morning" if hour < 12 else
            "Good afternoon" if hour < 18 else "Good evening")
    who = name.split()[0] if name else honorific
    return f"{part}, {who}. Jardo here."


async def assemble_briefing(session: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    store = MemoryStore(session)
    owner = await store.get_owner()
    honorific = "ma" if (owner and owner.pronoun_style == "ma") else "sir"
    name = owner.name if owner else ""

    greeting = _time_greeting(now, honorific, name)

    updates: list[str] = []
    if owner is not None:
        pending = (await session.execute(
            select(func.count()).select_from(Approval).where(Approval.status == "pending")
        )).scalar_one()
        if pending:
            updates.append(
                f"{pending} action{'s' if pending != 1 else ''} "
                f"{'are' if pending != 1 else 'is'} waiting for your approval.")

        stats = await gather_stats(session, "daily")
        if stats.security_events:
            updates.append(
                f"I flagged {stats.security_events} security "
                f"event{'s' if stats.security_events != 1 else ''} in the last day.")
        if stats.facts_learned:
            updates.append(
                f"I learned {stats.facts_learned} new thing"
                f"{'s' if stats.facts_learned != 1 else ''} about how you like to work.")
        if stats.saved_usd >= 0.01:
            updates.append(
                f"I saved about ${stats.saved_usd:.2f} by handling tasks locally.")
        if stats.chat_messages:
            updates.append(f"We exchanged {stats.chat_messages} messages.")

    # If an objective from a prior session is still active, surface it.
    active = (await session.execute(
        select(SupervisionSession).where(SupervisionSession.status == "active")
        .order_by(SupervisionSession.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    has_updates = bool(updates)
    if not has_updates:
        updates.append("Nothing needs your attention — a clean slate.")

    prompt = "What would you like to achieve today?"

    # A single spoken paragraph: greeting → updates → the day's question.
    spoken = greeting
    if has_updates:
        spoken += " Here's where things stand. " + " ".join(updates)
    spoken += " " + prompt

    return {
        "greeting": greeting,
        "updates": updates,
        "has_updates": has_updates,
        "active_objective": active.objective if active else None,
        "prompt": prompt,
        "spoken": spoken,
        "owner": bool(owner),
    }
