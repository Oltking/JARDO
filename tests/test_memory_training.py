"""Memory hygiene (the 'memory of you' training): bounded injection, and the
ability to forget wrong/auto-extracted facts so a bad extraction isn't permanent."""

from core.memory import MemoryStore
from core.schema import Owner


async def _owner(session) -> Owner:
    owner = Owner(name="Mem Test", pronoun_style="sir", email="mem@example.test",
                  device_public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    session.add(owner)
    await session.commit()
    return owner


async def test_list_facts_is_bounded_and_oldest_first(session):
    owner = await _owner(session)
    store = MemoryStore(session)
    for i in range(60):
        await store.add_fact(owner.id, f"fact number {i}", source="chat")
    await session.commit()
    facts = await store.list_facts(owner.id, limit=40)
    assert len(facts) == 40  # bounded — never the full 60 into the prompt
    # Most-recent kept, returned oldest-first for a stable prompt.
    assert facts[0].content == "fact number 20"
    assert facts[-1].content == "fact number 59"


async def test_forget_by_source_clears_only_that_source(session):
    owner = await _owner(session)
    store = MemoryStore(session)
    await store.add_fact(owner.id, "owner prefers pnpm", source="chat")
    await store.add_fact(owner.id, "auto extracted junk", source="worker")
    await store.add_fact(owner.id, "more junk", source="worker")
    await session.commit()

    removed = await store.forget_by_source(owner.id, "worker")
    await session.commit()
    assert removed == 2
    remaining = await store.list_facts(owner.id)
    assert [m.content for m in remaining] == ["owner prefers pnpm"]


async def test_forget_by_id_is_owner_scoped(session):
    owner = await _owner(session)
    store = MemoryStore(session)
    fact = await store.add_fact(owner.id, "delete me", source="chat")
    await session.commit()

    assert await store.forget(owner.id, fact.id) is True
    await session.commit()
    assert await store.list_facts(owner.id) == []
    # Forgetting a non-existent id is a safe no-op.
    import uuid
    assert await store.forget(owner.id, uuid.uuid4()) is False
