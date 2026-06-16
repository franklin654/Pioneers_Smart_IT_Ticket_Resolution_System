"""Async engine, session factory, and the FastAPI session dependency.

Single connection pool for the whole process (CLAUDE.md backend §9 — never
open a new connection per request). Transactions are opened by the service
layer, not here; this module only hands out sessions and disposes the engine
on shutdown.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import get_settings
from src.db.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            echo=settings.db_echo,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False
        )
    return _session_factory


async def init_db() -> None:
    """Create tables if they don't exist. Called once from the app lifespan.

    Real schema provisioning (extension creation, enum upgrades, indexes) lives
    in `scripts/setup_db.py` — this is a thin idempotent safety net for local
    dev/tests, not the source of truth for production migrations.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — one session per request, always closed."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for code outside a request (background tasks, scripts).

    Background work must never share the request's session — see
    docs/03_BACKEND_DESIGN.md's "background task session isolation" invariant.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
