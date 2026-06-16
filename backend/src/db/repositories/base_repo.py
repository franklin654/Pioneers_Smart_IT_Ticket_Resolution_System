"""Generic repository base. All DB queries live in this layer — nowhere else
(CLAUDE.md backend §9). Repositories never manage their own transactions;
the service/orchestrator layer opens and commits them.
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id_: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def create(self, **kwargs: object) -> ModelT:
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def delete(self, obj: ModelT) -> None:
        # NOTE: docs/03_BACKEND_DESIGN.md's "audit fix C2" claims `AsyncSession.delete()`
        # is synchronous and that `await`-ing it is the v1 bug. That's backwards for the
        # SQLAlchemy version this project pins (2.0.51): `AsyncSession.delete` is an
        # `async def` — its own docstring says it's awaitable because cascading deletes
        # may need to load unloaded relationships. Confirmed by a failing integration
        # test: without `await`, the coroutine is silently never scheduled and the row
        # is never deleted (RuntimeWarning: "coroutine 'AsyncSession.delete' was never
        # awaited"). Awaiting it here is correct; not awaiting it is the actual bug.
        await self.session.delete(obj)
        await self.session.flush()

    async def exists(self, id_: uuid.UUID) -> bool:
        result = await self.session.execute(select(self.model.id).where(self.model.id == id_))
        return result.scalar_one_or_none() is not None
