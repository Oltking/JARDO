import uuid

from core.memory import MemoryStore
from core.schema import Owner


async def _make_owner(session) -> Owner:
    owner = Owner(
        name="Test Owner",
        pronoun_style="sir",
        email=f"{uuid.uuid4().hex[:8]}@example.test",
        device_public_key="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
    )
    session.add(owner)
    await session.flush()
    return owner


async def test_fact_roundtrip_and_dedupe(session):
    store = MemoryStore(session)
    owner = await _make_owner(session)

    first = await store.add_fact(owner.id, "Prefers concise answers")
    duplicate = await store.add_fact(owner.id, "Prefers concise answers")
    assert first is not None
    assert duplicate is None  # naive dedupe

    facts = await store.list_facts(owner.id)
    assert [f.content for f in facts] == ["Prefers concise answers"]


async def test_conversation_history_window(session):
    store = MemoryStore(session)
    owner = await _make_owner(session)
    conversation = await store.create_conversation(owner.id, "hello world")

    for i in range(6):
        await store.add_message(conversation.id, "user", f"msg {i}")

    recent = await store.recent_messages(conversation.id, limit=4)
    assert [m.content for m in recent] == ["msg 2", "msg 3", "msg 4", "msg 5"]
    assert recent[0].created_at <= recent[-1].created_at  # chronological order


async def test_message_records_usage_for_cost_router(session):
    store = MemoryStore(session)
    owner = await _make_owner(session)
    conversation = await store.create_conversation(owner.id, "usage")
    message = await store.add_message(
        conversation.id, "assistant", "hi",
        model="accounts/fireworks/models/gpt-oss-20b",
        prompt_tokens=10, completion_tokens=5,
    )
    assert message.prompt_tokens == 10
    assert message.completion_tokens == 5
