"""Reporter (spec §4.4): hourly / daily / weekly reports from the logs.

Data sources (all already written by earlier phases):
  - routing_log  → cost spent, spend avoided by routing, local-vs-remote split (§5.5)
  - audit_log    → tasks/events; "security.event" rows are anomalies (§6.6)
  - messages     → chat volume + token usage

Reports are stored in the reports table (searchable) and surfaced in the in-app
inbox / desktop app. Delivery beyond storage (email) is deferred (QUESTIONS.md Q6).

Pure functions of a time window so they are trivially testable and reproducible.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schema import AuditLog, Message, Report, RoutingLog

_PERIOD_DELTA = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


@dataclass
class ReportStats:
    period: str
    window_start: datetime
    window_end: datetime
    routed_calls: int
    fireworks_calls: int
    local_calls: int
    spent_usd: float
    saved_usd: float
    chat_messages: int
    tokens: int
    security_events: int
    facts_learned: int

    def as_dict(self) -> dict:
        return {
            "period": self.period,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "routed_calls": self.routed_calls,
            "fireworks_calls": self.fireworks_calls,
            "local_calls": self.local_calls,
            "spent_usd": round(self.spent_usd, 5),
            "saved_usd": round(self.saved_usd, 5),
            "chat_messages": self.chat_messages,
            "tokens": self.tokens,
            "security_events": self.security_events,
            "facts_learned": self.facts_learned,
        }


async def gather_stats(session: AsyncSession, period: str,
                       now: datetime | None = None) -> ReportStats:
    if period not in _PERIOD_DELTA:
        raise ValueError(f"unknown period {period!r}")
    end = now or datetime.now(timezone.utc)
    start = end - _PERIOD_DELTA[period]

    def in_window(column):
        return column >= start, column < end

    routing_rows = (await session.execute(
        select(RoutingLog).where(*in_window(RoutingLog.ts))
    )).scalars().all()
    spent = sum(r.est_cost_usd for r in routing_rows if r.backend == "fireworks")
    saved = sum(r.saved_usd for r in routing_rows)
    fw = sum(1 for r in routing_rows if r.backend == "fireworks")
    local = sum(1 for r in routing_rows if r.backend in ("ollama", "vllm"))

    chat_count = (await session.execute(
        select(func.count()).select_from(Message).where(*in_window(Message.created_at))
    )).scalar_one()
    tokens = (await session.execute(
        select(func.coalesce(
            func.sum(func.coalesce(Message.prompt_tokens, 0)
                     + func.coalesce(Message.completion_tokens, 0)), 0)
        ).where(*in_window(Message.created_at))
    )).scalar_one()
    security = (await session.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.event_type == "security.event", *in_window(AuditLog.ts))
    )).scalar_one()
    # detail is generic JSON (not JSONB), so sum the counts in Python.
    fact_rows = (await session.execute(
        select(AuditLog.detail).where(
            AuditLog.event_type == "memory.facts_extracted", *in_window(AuditLog.ts))
    )).scalars().all()
    facts = sum(int(d.get("count", 0)) for d in fact_rows if isinstance(d, dict))

    return ReportStats(
        period=period, window_start=start, window_end=end,
        routed_calls=len(routing_rows), fireworks_calls=fw, local_calls=local,
        spent_usd=float(spent), saved_usd=float(saved),
        chat_messages=int(chat_count), tokens=int(tokens),
        security_events=int(security), facts_learned=int(facts or 0),
    )


def render_body(stats: ReportStats, honorific: str = "sir") -> str:
    """Persona-flavoured narrative (spec §4.4 tone by period)."""
    s = stats
    if s.period == "hourly":  # terse
        parts = [f"Past hour: {s.chat_messages} messages, {s.routed_calls} routed calls, "
                 f"${s.spent_usd:.4f} spent (${s.saved_usd:.4f} saved by routing)."]
        if s.security_events:
            parts.append(f"⚠ {s.security_events} security event(s) flagged — see audit log.")
        return " ".join(parts)

    lines = [f"Jardo {s.period} report, {honorific}.",
             f"Window: {s.window_start:%Y-%m-%d %H:%M} → {s.window_end:%Y-%m-%d %H:%M} UTC.",
             "",
             f"• Conversation: {s.chat_messages} messages, {s.tokens} tokens.",
             f"• Model routing: {s.routed_calls} calls "
             f"({s.local_calls} local / {s.fireworks_calls} Fireworks).",
             f"• Cost: ${s.spent_usd:.4f} spent, ${s.saved_usd:.4f} avoided by routing local-first.",
             f"• Memory: {s.facts_learned} new fact(s) learned.",
             f"• Security: {s.security_events} event(s) at or above medium severity."]
    if s.period == "weekly":
        share = (100 * s.local_calls / s.routed_calls) if s.routed_calls else 0
        lines += ["", f"Trend: {share:.0f}% of calls served locally at zero marginal cost."]
    if s.period == "daily":
        lines += ["", "Tomorrow: awaiting your intent (morning intent request, §4.5)."]
        if s.security_events:
            lines.append("Question for you: review the flagged security events above?")
    return "\n".join(lines)


async def generate_report(session: AsyncSession, period: str, honorific: str = "sir",
                          now: datetime | None = None) -> Report:
    stats = await gather_stats(session, period, now=now)
    report = Report(
        period=period, window_start=stats.window_start, window_end=stats.window_end,
        body=render_body(stats, honorific), stats=stats.as_dict(),
    )
    session.add(report)
    await session.flush()
    return report
