"""Idempotent database initialisation script.

Creates the PostgreSQL schema, enables the pgvector extension, and builds
IVFFlat indexes on embedding columns.  Safe to run on every deployment
because all DDL uses ``IF NOT EXISTS`` semantics.

Usage::

    # From the backend/ directory
    python -m scripts.setup_db

Environment:
    DATABASE_URL: Required.  Loaded from .env or the process environment.
"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models import Base

logger = get_logger(__name__)


async def setup() -> None:
    """Run all DDL steps required to initialise the database."""
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url), echo=True)

    async with engine.begin() as conn:
        logger.info("Enabling pgvector extension")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        logger.info("Creating ORM tables")
        await conn.run_sync(Base.metadata.create_all)

        logger.info("Creating IVFFlat index on ticket_embeddings")
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ticket_embeddings_ivfflat
            ON ticket_embeddings USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """))

        logger.info("Creating IVFFlat index on knowledge_base_entries")
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_kb_entries_ivfflat
            ON knowledge_base_entries USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """))

        logger.info("Creating B-tree indexes on frequently filtered columns")
        for stmt in [
            "CREATE INDEX IF NOT EXISTS ix_tickets_source ON tickets (source)",
            "CREATE INDEX IF NOT EXISTS ix_tickets_created_at ON tickets (created_at)",
            "CREATE INDEX IF NOT EXISTS ix_kb_category ON knowledge_base_entries (category)",
        ]:
            await conn.execute(text(stmt))

    await engine.dispose()
    logger.info("Database setup complete")


if __name__ == "__main__":
    try:
        asyncio.run(setup())
    except Exception as exc:
        logger.error("Database setup failed", extra={"metadata": {"error": str(exc)}})
        sys.exit(1)
