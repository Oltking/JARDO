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


class Policy(Base):
    """Permission Broker tiers (spec §6.5): owner-defined action policies."""

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    target_pattern: Mapped[str] = mapped_column(String(500))  # regex, fullmatch
    tier: Mapped[str] = mapped_column(String(16))  # always-allow | ask-once | always-ask
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Approval(Base):
    """Escalated actions awaiting the owner (spec §6.5); UI arrives Phase 5."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(64))
    action_type: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(Text)
    stated_goal: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SupervisionSession(Base):
    """An owner-declared oversight objective (spec §4.3 necessity test, §4.5
    intent request). Before Jardo supervises a coding agent, the owner states
    what they want to achieve; every agent action is then judged against this
    objective. One active session per owner at a time (MVP)."""

    __tablename__ = "supervision_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), index=True)
    objective: Mapped[str] = mapped_column(Text)     # what the owner wants achieved
    agent: Mapped[str] = mapped_column(String(64), default="any")  # scope, e.g. claude-code
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


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


class Task(Base):
    """Orchestrator work item (spec §4.2): one-at-a-time durable executor.

    Lifecycle: pending → verifying → executing → (done | failed);
    a failed attempt with retries left returns to pending with next_run_at set.
    checkpoint holds resumable state so a crash mid-run doesn't lose progress.
    """

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))       # chat | action | goal
    goal: Mapped[str] = mapped_column(Text)
    spec: Mapped[dict] = mapped_column(JSON, default=dict)      # the request payload
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Report(Base):
    """Generated reports (spec §4.4): stored and searchable, in-app inbox."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    period: Mapped[str] = mapped_column(String(8), index=True)  # hourly | daily | weekly
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    body: Mapped[str] = mapped_column(Text)  # human-readable narrative
    stats: Mapped[dict] = mapped_column(JSON, default=dict)  # machine-readable roll-up
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
