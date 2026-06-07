"""Async SQLAlchemy engine and session factory.

A single module-level ``engine`` and ``AsyncSessionLocal`` factory are
created at import time using the application settings.  The ``get_db``
async generator is intended for use as a FastAPI dependency.

Usage (FastAPI)::

    @router.post("/tickets")
    async def create_ticket(db: AsyncSession = Depends(get_db)):
        repo = TicketRepository(db)
        ...

Usage (scripts / tests)::

    async with AsyncSessionLocal() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_by_id(ticket_id)
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)


def _build_engine():
    """Create the async engine from application settings."""
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        echo=settings.db_echo,
        pool_pre_ping=True,  # validate connections before use
    )


engine = _build_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep ORM objects usable after commit
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields one ``AsyncSession`` per request.

    Commits on clean exit, rolls back on any exception so partial writes
    never reach the database.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all ORM tables and enable the pgvector extension.

    Idempotent — safe to call on every application startup.
    IVFFlat indexes are created here too so ``setup_db.py`` and the
    FastAPI lifespan hook both use the same logic.
    """
    from src.db.models import Base  # local import avoids circular dependency

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

        # IVFFlat indexes — created only if they don't already exist
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ticket_embeddings_ivfflat
            ON ticket_embeddings USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_kb_entries_ivfflat
            ON knowledge_base_entries USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """))

    logger.info("Database initialized", extra={"metadata": {"action": "init_db"}})


async def check_db_health() -> bool:
    """Execute ``SELECT 1`` to verify the database connection is alive.

    Returns:
        ``True`` if the database responded, ``False`` otherwise.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error(
            "Database health check failed",
            extra={"metadata": {"error": str(exc)}},
        )
        return False
