"""Idempotent database provisioning. Safe to re-run against an empty *or* an
already-provisioned database.

No Alembic for this MVP timeline (`docs/03_BACKEND_DESIGN.md`) — `create_all`
plus a small amount of raw, idempotent DDL covers:

1. The `vector` extension (required before any `Vector(384)` column can exist).
2. All six tables + enum types, via `Base.metadata.create_all` (checks
   `pg_type`/`pg_class` first, so re-running is a no-op on an up-to-date DB).
3. `ALTER TYPE ticket_status ADD VALUE IF NOT EXISTS 'awaiting_review'` — native
   Postgres enums aren't altered by `create_all` on a database that already has
   an older `ticket_status` type (i.e. a v1 deployment being upgraded in place).
   Run for every current enum value, not just the new one, so this script is
   also correct against a from-scratch v1-shaped type.
4. An IVFFlat ANN index on `knowledge_base_entries.embedding` (cosine ops,
   lists=100) — created only after the column exists, `IF NOT EXISTS`.

Usage:
    python scripts/setup_db.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.database import get_engine
from src.db.models import Base, TicketStatus

logger = get_logger(__name__)

_ENUM_NAME_TO_VALUES = {
    "ticket_status": [s.value for s in TicketStatus],
}


async def _create_vector_extension(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    logger.info("vector_extension_ready")


async def _create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("tables_ready")


async def _upgrade_enum_values(engine: AsyncEngine) -> None:
    """`ADD VALUE IF NOT EXISTS` must run outside an open transaction block in
    Postgres < 12 and is safest run autocommit on every version, so each
    statement gets its own connection at AUTOCOMMIT isolation.

    `ALTER TYPE ... ADD VALUE` takes the value as a DDL literal — asyncpg
    cannot bind it as a query parameter. That's safe here only because
    `enum_name`/`value` come exclusively from `_ENUM_NAME_TO_VALUES`, a
    hardcoded, code-controlled table — never from user input (unlike every
    other query in this codebase, which must use bound parameters).
    """
    for enum_name, values in _ENUM_NAME_TO_VALUES.items():
        for value in values:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")
                )
    logger.info("enum_values_upgraded", enums=list(_ENUM_NAME_TO_VALUES))


async def _create_kb_ann_index(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_kb_entries_embedding_ivfflat "
                "ON knowledge_base_entries USING ivfflat (embedding vector_cosine_ops) "
                "WITH (lists = 100)"
            )
        )
    logger.info("kb_ann_index_ready")


async def setup_database() -> None:
    settings = get_settings()
    engine = get_engine()
    logger.info("setup_db_start", environment=settings.environment)

    await _create_vector_extension(engine)
    await _create_tables(engine)
    await _upgrade_enum_values(engine)
    await _create_kb_ann_index(engine)

    await engine.dispose()
    logger.info("setup_db_complete")


def main() -> None:
    configure_logging()
    asyncio.run(setup_database())


if __name__ == "__main__":
    main()
