"""Response cache — the cost-optimization core: never pay twice for an answer."""

from core.cache import cache_key, cache_stats, cached_call, get_cached, put_cached


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
