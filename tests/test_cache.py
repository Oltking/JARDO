"""Response cache — the cost-optimization core: never pay twice for an answer."""

import pytest
from sqlalchemy import text

import core.cache as cache_mod
from core.cache import (
    cache_key,
    cache_stats,
    cached_call,
    get_cached,
    put_cached,
    semantic_get,
)


@pytest.fixture(autouse=True)
def _no_embed(monkeypatch):
    """Default: no embedding model — exact cache only (avoids network in tests)."""
    async def none(_text):
        return None
    monkeypatch.setattr(cache_mod, "embed", none)


async def test_key_is_stable_and_whitespace_insensitive():
    a = cache_key("m", [{"role": "user", "content": "hello   world"}])
    b = cache_key("m", [{"role": "user", "content": "hello world"}])
    assert a == b
    c = cache_key("m", [{"role": "user", "content": "different"}])
    assert a != c
    # different model → different key
    assert cache_key("m2", [{"role": "user", "content": "hello world"}]) != a


async def test_put_then_get(session):
    msgs = [{"role": "user", "content": "what is 2+2"}]
    assert await get_cached(session, "m", msgs) is None
    await put_cached(session, "m", msgs, "4", per_call_tokens=50)
    assert await get_cached(session, "m", msgs) == "4"


async def test_cached_call_runs_miss_once_then_serves_cache(session):
    calls = {"n": 0}

    async def miss():
        calls["n"] += 1
        return "the answer", 120

    msgs = [{"role": "user", "content": "expensive question"}]
    first = await cached_call(session, "big-model", msgs, miss)
    assert first.cached is False and first.content == "the answer"

    second = await cached_call(session, "big-model", msgs, miss)
    assert second.cached is True
    assert second.content == "the answer"
    assert second.tokens_saved == 120
    assert calls["n"] == 1  # miss_fn (the paid call) ran only once


async def test_stats_track_savings(session):
    async def miss():
        return "x", 100

    msgs = [{"role": "user", "content": "repeated"}]
    await cached_call(session, "m", msgs, miss)   # miss (store)
    await cached_call(session, "m", msgs, miss)   # hit
    await cached_call(session, "m", msgs, miss)   # hit
    stats = await cache_stats(session)
    assert stats["entries"] == 1
    assert stats["total_hits"] == 2
    assert stats["tokens_saved"] == 200  # 2 hits × 100 tokens


async def test_semantic_cache_hit(session, monkeypatch):
    # Set up pgvector + the embedding column on the test table.
    await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await session.execute(
        text("ALTER TABLE response_cache ADD COLUMN IF NOT EXISTS embedding vector(768)"))
    await session.flush()

    # Fake embedder: any query about France maps to the same vector, others differ.
    async def fake_embed(t):
        base = 1.0 if "france" in t.lower() or "french" in t.lower() else -1.0
        return [base] + [0.0] * 767
    monkeypatch.setattr(cache_mod, "embed", fake_embed)

    calls = {"n": 0}

    async def miss():
        calls["n"] += 1
        return "Paris.", 90

    # First: a miss stores the answer + its embedding.
    q1 = [{"role": "user", "content": "what is the capital of France?"}]
    r1 = await cached_call(session, "m", q1, miss)
    assert r1.cached is False

    # A *differently worded* but semantically-similar question → semantic hit,
    # no new model call, tokens saved.
    q2 = [{"role": "user", "content": "tell me the French capital city"}]
    r2 = await cached_call(session, "m", q2, miss)
    assert r2.cached is True
    assert r2.content == "Paris."
    assert r2.tokens_saved == 90
    assert calls["n"] == 1  # the paid call ran only once

    # An unrelated question does NOT hit.
    q3 = [{"role": "user", "content": "how tall is Mount Everest?"}]
    r3 = await cached_call(session, "m", q3, miss)
    assert r3.cached is False
