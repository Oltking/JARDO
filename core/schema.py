"""Database schema (Phase 1).

Everything is keyed by owner_id from day one: identity is a per-user record
created at first-run setup (QUESTIONS.md Q2), never hardcoded. MVP is
single-owner (spec §11) but the schema doesn't assume it.

audit_log is append-only: migration 0001 installs a trigger rejecting
UPDATE/DELETE (SECURITY.md rule 5).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    pronoun_style: Mapped[str] = mapped_column(String(8))  # "sir" | "ma" (spec §1)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    device_public_key: Mapped[str] = mapped_column(Text)  # PEM; private half in Keychain
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # "fact" | "preference"
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="chat")  # chat | setup | worker
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="(untitled)")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # system | user | assistant
    content: Mapped[str] = mapped_column(Text)
    # Cost-router groundwork (§5): every model call records what it consumed.
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class RoutingLog(Base):
    """Every routing decision (spec §5.3): task_id, route, est/alt cost, saved_$."""

    __tablename__ = "routing_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    backend: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(120))
    task_label: Mapped[str] = mapped_column(String(16))
    est_cost_usd: Mapped[float] = mapped_column()
    alternative_cost_usd: Mapped[float] = mapped_column()
    saved_usd: Mapped[float] = mapped_column()
    actual_cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    floor: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(200))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    actor: Mapped[str] = mapped_column(String(64))  # "core", "worker", "cli", later: agent ids
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
