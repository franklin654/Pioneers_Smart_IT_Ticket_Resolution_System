"""Integration-test fixtures: a real Postgres+pgvector container (session-
scoped, plain sync fixture — no event loop involved in starting it), and a
fresh async engine/session per test, wrapped in an outer transaction that's
rolled back at teardown (SQLAlchemy's SAVEPOINT-nesting pattern via
`join_transaction_mode`) so tests stay independent even though repository
code calls `session.commit()`/`flush()` internally.

Engines/connections are *not* shared across tests: pytest-asyncio 0.24 gives
each test function its own event loop by default, and asyncpg connections
can't be reused across event loops — sharing a session-scoped engine here
produced "got Future attached to a different loop" errors.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.db.models import Base
from src.ingestion.pii_masker import PIIMasker


@pytest.fixture(scope="session")
def pii_masker() -> PIIMasker:
    """Constructing this loads a spaCy model — expensive, so it's built once
    per test session and shared. Safe to share across tests with different
    event loops: it holds no asyncio-loop-bound resources (CPU-only Presidio
    engines), only `asyncio.to_thread()` touches the event loop, transiently."""
    return PIIMasker()


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    """Container URL, with the schema provisioned exactly once via a
    throwaway event loop independent of pytest-asyncio's per-test loops."""
    url = postgres_container.get_connection_url()

    async def _provision() -> None:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_provision())
    return url


@pytest_asyncio.fixture
async def db_session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url)
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await outer_transaction.rollback()
    await connection.close()
    await engine.dispose()
