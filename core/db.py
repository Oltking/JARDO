"""Async SQLAlchemy engine/session plumbing.

Dual-mode (spec §5 packaging): Postgres for the dev/server setup (pgvector +
Redis), and SQLite for the self-contained desktop build (no services, one file).
The models are portable (generic Uuid, JSON, timezone datetimes); only the
semantic cache (pgvector) is Postgres-only and degrades to exact-match on SQLite.
"""

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings


class Base(DeclarativeBase):
    pass


def is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if is_sqlite() else {},
)

if is_sqlite():
    # SQLite ignores foreign keys unless told to enforce them, per connection.
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_fk_on(dbapi_conn, _record):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create tables directly from the models. Used on SQLite (the embedded
    build), where the Postgres-specific Alembic migrations don't apply. Safe to
    call on every startup — create_all only makes missing tables."""
    import core.schema  # noqa: F401 — ensure models are registered on Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionFactory() as session:
        yield session
