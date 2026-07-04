"""Test fixtures. Integration tests use a dedicated jardo_test database on the
dockerized Postgres (infra/docker-compose.yml) so dev data is never touched.

Engine is function-scoped: pytest-asyncio gives each test its own event loop,
and asyncpg connections must not cross loops."""

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db import Base
import core.schema  # noqa: F401

ADMIN_DSN = "postgresql://jardo:jardo-dev-only@127.0.0.1:5432/postgres"
TEST_URL = "postgresql+asyncpg://jardo:jardo-dev-only@127.0.0.1:5432/jardo_test"


@pytest.fixture
async def session():
    conn = await asyncpg.connect(ADMIN_DSN)
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname='jardo_test'")
    if not exists:
        await conn.execute("CREATE DATABASE jardo_test")
    await conn.close()

    engine = create_async_engine(TEST_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
