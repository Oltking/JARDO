"""Memory access layer: facts/preferences + conversation persistence."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schema import AuditLog, Conversation, Memory, Message, Owner


class MemoryStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    # -- owner ------------------------------------------------------------
    async def get_owner(self) -> Owner | None:
        """MVP: single owner — first (only) row. Schema supports more (Q2)."""
        return (await self.session.execute(select(Owner).limit(1))).scalar_one_or_none()

    # -- facts ------------------------------------------------------------
    async def add_fact(
        self, owner_id: uuid.UUID, content: str, kind: str = "fact", source: str = "chat"
    ) -> Memory | None:
        """Insert a memory unless an identical one exists (naive dedupe)."""
        existing = await self.session.execute(
            select(Memory).where(Memory.owner_id == owner_id, Memory.content == content)
        )
        if existing.scalar_one_or_none() is not None:
            return None
        memory = Memory(owner_id=owner_id, kind=kind, content=content, source=source)
        self.session.add(memory)
        await self.session.flush()
        return memory

    async def list_facts(self, owner_id: uuid.UUID) -> list[Memory]:
        rows = await self.session.execute(
            select(Memory).where(Memory.owner_id == owner_id).order_by(Memory.created_at)
        )
        return list(rows.scalars())

    # -- conversations ----------------------------------------------------
    async def create_conversation(self, owner_id: uuid.UUID, title: str) -> Conversation:
        conversation = Conversation(owner_id=owner_id, title=title[:200])
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return await self.session.get(Conversation, conversation_id)

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        model: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def recent_messages(self, conversation_id: uuid.UUID, limit: int) -> list[Message]:
        rows = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(rows.scalars().all()))

    # -- audit ------------------------------------------------------------
    async def audit(self, actor: str, event_type: str, detail: dict) -> None:
        self.session.add(AuditLog(actor=actor, event_type=event_type, detail=detail))
        await self.session.flush()
