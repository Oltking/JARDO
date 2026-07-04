"""Daily spend tracking + routing decision log (spec §5.3: log every decision)."""

from datetime import datetime, timezone

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.router.router import RouteDecision
from core.schema import RoutingLog


async def log_decision(session: AsyncSession, decision: RouteDecision,
                       task_id: str, actual_cost_usd: float | None = None) -> None:
    session.add(RoutingLog(
        task_id=task_id,
        backend=decision.backend,
        model=decision.model,
        task_label=decision.task_label,
        est_cost_usd=decision.est_cost_usd,
        alternative_cost_usd=decision.alternative_cost_usd,
        saved_usd=decision.saved_usd,
        actual_cost_usd=actual_cost_usd,
        floor=decision.floor,
        reason=decision.reason,
    ))
    await session.flush()


async def spent_today_usd(session: AsyncSession) -> float:
    """Sum of today's estimated remote spend (UTC day)."""
    today = datetime.now(timezone.utc).date()
    result = await session.execute(
        select(func.coalesce(func.sum(RoutingLog.est_cost_usd), 0.0)).where(
            cast(RoutingLog.ts, Date) == today,
            RoutingLog.backend == "fireworks",
        )
    )
    return float(result.scalar_one())
