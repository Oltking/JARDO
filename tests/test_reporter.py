from datetime import datetime, timedelta, timezone

import pytest

from core.reporter import gather_stats, generate_report, render_body
from core.schema import AuditLog, Conversation, Message, Owner, RoutingLog


async def _seed(session):
    owner = Owner(name="Rep Test", pronoun_style="ma", email="rep@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.flush()
    convo = Conversation(owner_id=owner.id, title="t")
    session.add(convo)
    await session.flush()

    now = datetime.now(timezone.utc)
    session.add_all([
        Message(conversation_id=convo.id, role="assistant", content="hi",
                model="qwen2.5:0.5b", prompt_tokens=10, completion_tokens=5),
        RoutingLog(ts=now, task_id="t1", backend="ollama", model="qwen2.5:0.5b",
                   task_label="trivial", est_cost_usd=0.0, alternative_cost_usd=0.001,
                   saved_usd=0.001, actual_cost_usd=None, floor="bootstrap", reason="local"),
        RoutingLog(ts=now, task_id="t2", backend="fireworks",
                   model="fireworks/kimi-k2p6", task_label="critical",
                   est_cost_usd=0.02, alternative_cost_usd=0.02, saved_usd=0.0,
                   actual_cost_usd=0.02, floor="bootstrap", reason="critical"),
        AuditLog(ts=now, actor="sentinel", event_type="security.event",
                 detail={"severity": "high"}),
        AuditLog(ts=now, actor="worker", event_type="memory.facts_extracted",
                 detail={"count": 3}),
    ])
    await session.flush()
    return owner


async def test_gather_stats_rolls_up_window(session):
    await _seed(session)
    stats = await gather_stats(session, "daily")
    assert stats.routed_calls == 2
    assert stats.local_calls == 1 and stats.fireworks_calls == 1
    assert stats.spent_usd == pytest.approx(0.02)
    assert stats.saved_usd == pytest.approx(0.001)
    assert stats.tokens == 15
    assert stats.security_events == 1
    assert stats.facts_learned == 3


async def test_events_outside_window_excluded(session):
    await _seed(session)
    # hourly window still contains the just-seeded rows...
    assert (await gather_stats(session, "hourly")).routed_calls == 2
    # ...but a window ending 2 days ago contains nothing.
    old_now = datetime.now(timezone.utc) - timedelta(days=2)
    assert (await gather_stats(session, "daily", now=old_now)).routed_calls == 0


async def test_render_uses_owner_honorific(session):
    await _seed(session)
    stats = await gather_stats(session, "daily")
    assert "ma" in render_body(stats, "ma")


async def test_generate_report_persists_and_scores(session):
    await _seed(session)
    report = await generate_report(session, "weekly", honorific="ma")
    assert report.period == "weekly"
    assert report.stats["local_calls"] == 1
    assert "served locally" in report.body  # weekly trend line


async def test_unknown_period_rejected(session):
    with pytest.raises(ValueError, match="unknown period"):
        await gather_stats(session, "monthly")
