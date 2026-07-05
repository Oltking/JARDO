"""Response cache (spec §5 cost optimization).

Every model call is keyed by a stable hash of (model, messages). A cache hit
returns the stored answer with **zero tokens spent** — the single biggest cost
lever after local-first routing, especially for the repeated deterministic calls
Jardo makes while supervising (alignment judgments, classifications, extractions).

`cached_call` wraps any model call: check cache → on miss, run the real call and
store it. Normalization (whitespace-collapsed message contents) widens hits.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schema import ResponseCache


def cache_key(model: str, messages: list[dict]) -> str:
    norm = [{"role": m.get("role", ""),
             "content": " ".join(str(m.get("content", "")).split())} for m in messages]
    blob = json.dumps({"model": model, "messages": norm}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class CachedResult:
    content: str
    cached: bool
    tokens_saved: int


async def get_cached(session: AsyncSession, model: str, messages: list[dict]) -> str | None:
    key = cache_key(model, messages)
    row = (await session.execute(
        select(ResponseCache).where(ResponseCache.cache_key == key)
    )).scalar_one_or_none()
    if row is None:
        return None
    row.hits += 1
    row.last_hit_at = datetime.now(timezone.utc)
    await session.flush()
    return row.response


async def put_cached(session: AsyncSession, model: str, messages: list[dict],
                     response: str, per_call_tokens: int) -> None:
    key = cache_key(model, messages)
    exists = (await session.execute(
        select(ResponseCache.id).where(ResponseCache.cache_key == key)
    )).first()
    if exists:
        return
    preview = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            preview = str(m.get("content", ""))[:300]
            break
    session.add(ResponseCache(cache_key=key, model=model, request_preview=preview,
                              response=response, per_call_tokens=per_call_tokens, hits=0))
    await session.flush()


async def cached_call(session: AsyncSession, model: str, messages: list[dict],
                      miss_fn: Callable[[], Awaitable[tuple[str, int]]]) -> CachedResult:
    """Return a cached response if present, else call miss_fn() -> (text, tokens)
    and store it. Zero tokens on a hit."""
    hit = await get_cached(session, model, messages)
    if hit is not None:
        # tokens this call would have cost = the stored per_call_tokens
        key = cache_key(model, messages)
        row = (await session.execute(
            select(ResponseCache).where(ResponseCache.cache_key == key)
        )).scalar_one()
        return CachedResult(hit, True, row.per_call_tokens)
    text, tokens = await miss_fn()
    await put_cached(session, model, messages, text, tokens)
    return CachedResult(text, False, 0)


async def cache_stats(session: AsyncSession) -> dict:
    entries = (await session.execute(
        select(func.count()).select_from(ResponseCache))).scalar_one()
    total_hits = (await session.execute(
        select(func.coalesce(func.sum(ResponseCache.hits), 0)))).scalar_one()
    tokens_saved = (await session.execute(
        select(func.coalesce(func.sum(ResponseCache.hits * ResponseCache.per_call_tokens), 0))
    )).scalar_one()
    return {"entries": int(entries), "total_hits": int(total_hits),
            "tokens_saved": int(tokens_saved)}
