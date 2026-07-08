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


async def savings_summary(session: AsyncSession) -> dict:
    """Make the cost-optimization value visible (spec §5): what the owner spent,
    what Jardo saved by routing cheap + caching, and how much ran free locally."""
    from core.cache import cache_stats

    async def _sum(col, *where):
        stmt = select(func.coalesce(func.sum(col), 0.0))
        for w in where:
            stmt = stmt.where(w)
        return float((await session.execute(stmt)).scalar_one())

    async def _count(*where):
        stmt = select(func.count()).select_from(RoutingLog)
        for w in where:
            stmt = stmt.where(w)
        return int((await session.execute(stmt)).scalar_one())

    spent = await _sum(RoutingLog.actual_cost_usd)
    saved = await _sum(RoutingLog.saved_usd)
    local = await _count(RoutingLog.backend.in_(("ollama", "vllm")))
    cloud = await _count(RoutingLog.backend == "fireworks")
    cache = await cache_stats(session)
    total = local + cloud
    return {
        "spent_usd": round(spent, 4),
        "saved_usd": round(saved, 4),
        "local_requests": local,
        "cloud_requests": cloud,
        "local_pct": round(100 * local / total) if total else 0,
        "cache_hits": cache.get("total_hits", 0),
        "tokens_saved": cache.get("tokens_saved", 0),
    }
