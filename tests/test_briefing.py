from datetime import datetime

from core.briefing import assemble_briefing
from core.schema import Approval, Owner


async def _owner(session, pronoun="sir", name="Ada Lovelace") -> Owner:
    owner = Owner(name=name, pronoun_style=pronoun, email="a@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.flush()
    return owner


async def test_greeting_is_time_aware_and_named(session):
    await _owner(session, name="Ada Lovelace")
    morning = await assemble_briefing(session, now=datetime(2026, 7, 5, 9, 0))
    assert morning["greeting"].startswith("Good morning, Ada")
    evening = await assemble_briefing(session, now=datetime(2026, 7, 5, 20, 0))
    assert evening["greeting"].startswith("Good evening, Ada")


async def test_updates_include_pending_approvals(session):
    await _owner(session)
    session.add(Approval(actor="claude-code", action_type="shell.run",
                         target="rm x", stated_goal="cleanup", severity="high",
                         status="pending"))
    await session.flush()
    briefing = await assemble_briefing(session)
    assert any("waiting for your approval" in u for u in briefing["updates"])
    assert briefing["has_updates"]


async def test_clean_slate_when_nothing_notable(session):
    await _owner(session)
    briefing = await assemble_briefing(session)
    assert briefing["has_updates"] is False
    assert "clean slate" in briefing["updates"][0]


async def test_spoken_includes_greeting_and_prompt(session):
    await _owner(session)
    briefing = await assemble_briefing(session)
    assert briefing["greeting"] in briefing["spoken"]
    assert briefing["prompt"] in briefing["spoken"]


async def test_no_owner_still_returns_greeting(session):
    briefing = await assemble_briefing(session)  # no owner seeded
    assert briefing["owner"] is False
    assert "Jardo here" in briefing["greeting"]
