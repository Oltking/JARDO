"""Away-mode report (Lane B): Jardo accounts for what it did while supervising,
built from the append-only audit log."""

from core.memory import MemoryStore
from core.schema import Owner
from core.supervision import session_report, start_session


async def _owner(session) -> Owner:
    o = Owner(name="Rep Test", pronoun_style="sir", email="rep@example.test",
              device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(o)
    await session.commit()
    return o


async def test_empty_report_when_nothing_happened(session):
    await _owner(session)
    r = await session_report(session)
    assert r["approved"] == 0 and r["declined"] == 0
    assert "haven't had to answer" in r["spoken"].lower()


async def test_report_counts_and_narrates(session):
    owner = await _owner(session)
    store = MemoryStore(session)
    await start_session(session, owner.id, "build the todo API", agent="claude")
    # Simulate a supervision run via the audit trail the tick writes.
    await store.audit("jardo", "terminal.answered",
                      {"action": "pytest -q", "approved": True, "reason": "safe", "pressed": True})
    await store.audit("jardo", "terminal.answered",
                      {"action": "git commit -m x", "approved": True, "reason": "safe", "pressed": True})
    await store.audit("jardo", "terminal.answered",
                      {"action": "rm -rf build", "approved": False,
                       "reason": "not safe", "pressed": True, "guided": True})
    await session.commit()

    r = await session_report(session)
    assert r["approved"] == 2
    assert r["declined"] == 1
    assert r["guided"] == 1
    assert "build the todo API" in r["spoken"]
    assert "approved 2" in r["spoken"]
    assert len(r["actions"]) == 3
