# Set required Settings fields before any module-level code (e.g. database.py
# engine creation) runs during test collection.  Unit tests never hit a real
# DB; integration tests override DATABASE_URL via TEST_DATABASE_URL.
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/ticket_routing_test",
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-minimum-32-characters!!")

"""Shared pytest fixtures for unit and integration tests.

Unit tests use no database — they rely on plain Python objects and mocks.
Integration tests require a real PostgreSQL instance with the pgvector
extension installed.  Set TEST_DATABASE_URL in your environment to point
at a dedicated test database (separate from the development database).

The ``db_session`` fixture wraps each test in a transaction that is rolled
back after the test completes, keeping the database clean without needing
to truncate tables between runs.
"""

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import (
    Base,
    KnowledgeBaseEntry,
    Ticket,
    TicketCategory,
    TicketSource,
    TicketStatus,
)

# ── Database URL ─────────────────────────────────────────────────────────────

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/ticket_routing_test",
)


# ── Session-scoped engine ─────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create the test engine, schema, and indexes once per session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ticket_embeddings_ivfflat
            ON ticket_embeddings USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_kb_entries_ivfflat
            ON knowledge_base_entries USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10)
        """))

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Per-test transaction rollback ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncSession:
    """Yield a session that rolls back all changes after each test.

    Uses a nested transaction (savepoint) so each test starts with the
    same database state as defined by the session-scoped schema creation.
    """
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ── Model factories ───────────────────────────────────────────────────────────


@pytest.fixture
def sample_ticket() -> Ticket:
    """Return an unsaved Ticket instance with sensible defaults."""
    return Ticket(
        title="Cannot connect to corporate VPN",
        description=(
            "User is unable to connect to the corporate VPN from a home network. "
            "Receiving 'Authentication failed' error after entering correct credentials."
        ),
        original_description=(
            "User is unable to connect to the corporate VPN from a home network. "
            "Receiving 'Authentication failed' error after entering correct credentials."
        ),
        category=TicketCategory.NETWORK,
        priority=2,
        status=TicketStatus.NEW,
        content_hash=uuid.uuid4().hex,  # unique per fixture call
        source=TicketSource.API,
        pii_detected=False,
    )


@pytest.fixture
def sample_kb_entry() -> KnowledgeBaseEntry:
    """Return an unsaved KnowledgeBaseEntry with sensible defaults."""
    return KnowledgeBaseEntry(
        title="VPN authentication failure",
        description="User cannot connect to VPN — authentication fails despite correct credentials.",
        category=TicketCategory.NETWORK,
        resolution=(
            "1. Clear cached VPN credentials from the OS keychain.\n"
            "2. Regenerate the user's MFA token in the identity provider.\n"
            "3. Reinstall the VPN client and reconfigure the server profile.\n"
            "4. Test connectivity on a different network to rule out ISP issues."
        ),
        source="kaggle",
    )
