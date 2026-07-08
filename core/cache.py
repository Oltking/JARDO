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

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import is_sqlite
from core.embeddings import embed, to_pgvector
from core.schema import ResponseCache

# Cosine-distance threshold for a semantic hit (0 = identical). Conservative so
# we only reuse genuinely equivalent prior answers.
_SEMANTIC_THRESHOLD = 0.12


def _query_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return " ".join(str(m.get("content", "")).split())
    return ""


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
                     response: str, per_call_tokens: int,
                     store_embedding: bool = False) -> None:
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
    # A savepoint so a concurrent request that inserted the same key first raises a
    # unique violation we can swallow — instead of poisoning the whole session
    # (audit LOW: cache write race).
    from sqlalchemy.exc import IntegrityError
    try:
        async with session.begin_nested():
            session.add(ResponseCache(cache_key=key, model=model,
                                      request_preview=preview, response=response,
                                      per_call_tokens=per_call_tokens, hits=0))
            await session.flush()
    except IntegrityError:
        return  # another request cached it first — fine, nothing to do
    # Only store the query embedding for semantic-eligible (single-shot) calls, so
    # context-dependent multi-turn entries can never be semantically cross-matched.
    # pgvector is Postgres-only; on SQLite (embedded build) the column doesn't
    # exist and we simply skip semantic caching (exact-match still works).
    if store_embedding and not is_sqlite():
        vec = await embed(_query_text(messages))
        if vec:
            await session.execute(
                text("UPDATE response_cache SET embedding = CAST(:v AS vector) "
                     "WHERE cache_key = :k"),
                {"v": to_pgvector(vec), "k": key})


async def semantic_get(session: AsyncSession, model: str,
                       messages: list[dict]) -> tuple[str, int] | None:
    """Find a cached answer to a *similar* prior query (same model) via pgvector.
    Returns (response, tokens_saved) or None. Skipped if no embedding model.

    Only entries stored with an embedding (single-shot calls) are candidates, so
    this is safe to use for stateless calls only (alignment, classification)."""
    if is_sqlite():
        return None  # no pgvector on the embedded build — exact-match only
    query = _query_text(messages)
    if not query:
        return None
    vec = await embed(query)
    if not vec:
        return None
    row = (await session.execute(
        text("SELECT id, response, per_call_tokens, "
             "(embedding <=> CAST(:v AS vector)) AS dist FROM response_cache "
             "WHERE model = :m AND embedding IS NOT NULL "
             "ORDER BY dist ASC LIMIT 1"),
        {"v": to_pgvector(vec), "m": model})).first()
    if row and row.dist is not None and row.dist <= _SEMANTIC_THRESHOLD:
        await session.execute(
            text("UPDATE response_cache SET hits = hits + 1, last_hit_at = now() "
                 "WHERE id = :id"), {"id": row.id})
        return row.response, row.per_call_tokens
    return None


async def cached_call(session: AsyncSession, model: str, messages: list[dict],
                      miss_fn: Callable[[], Awaitable[tuple[str, int]]],
                      allow_semantic: bool = False) -> CachedResult:
    """Return a cached response if present, else call miss_fn() -> (text, tokens)
    and store it. Zero tokens on a hit.

    allow_semantic: only pass True for STATELESS single-shot calls (a similar
    prior question is a safe reuse). Multi-turn / contextual calls must leave it
    False — otherwise a similarly-worded latest message could return a
    context-wrong answer."""
    # 1. Exact hit (always safe — keyed on the full message list).
    hit = await get_cached(session, model, messages)
    if hit is not None:
        key = cache_key(model, messages)
        row = (await session.execute(
            select(ResponseCache).where(ResponseCache.cache_key == key)
        )).scalar_one()
        return CachedResult(hit, True, row.per_call_tokens)
    # 2. Semantic hit — only for stateless calls (opt-in).
    if allow_semantic:
        sem = await semantic_get(session, model, messages)
        if sem is not None:
            response, tokens_saved = sem
            return CachedResult(response, True, tokens_saved)
    # 3. Miss — run the real call and store it.
    response, tokens = await miss_fn()
    await put_cached(session, model, messages, response, tokens,
                     store_embedding=allow_semantic)
    return CachedResult(response, False, 0)


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
