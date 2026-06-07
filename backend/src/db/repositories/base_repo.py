"""Generic async repository providing standard CRUD operations.

Subclasses declare their model class via the ``model_class`` class
attribute and inherit ``get_by_id``, ``create``, ``update``, ``delete``,
and ``list`` for free.

Example::

    class TicketRepository(BaseRepository[Ticket]):
        model_class = Ticket

        async def get_by_hash(self, content_hash: str) -> Ticket | None:
            ...
"""

import uuid
from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Thread-safe async repository for a single SQLAlchemy model.

    All methods accept an ``AsyncSession`` injected at construction time.
    No sessions are created inside the repository — session lifecycle
    is managed by the caller (FastAPI dependency or script).

    Args:
        session: An active ``AsyncSession`` to execute queries against.
    """

    model_class: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, record_id: uuid.UUID) -> ModelT | None:
        """Fetch a single record by primary key.

        Returns:
            The model instance, or ``None`` if not found.
        """
        return await self.session.get(self.model_class, record_id)

    async def create(self, obj: ModelT) -> ModelT:
        """Persist a new record and return it with all DB-generated defaults.

        Calls ``flush`` (not ``commit``) so the caller controls the
        transaction boundary.
        """
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, obj: ModelT) -> ModelT:
        """Merge a detached-or-modified instance back into the session.

        Returns the reattached, refreshed instance.
        """
        merged = await self.session.merge(obj)
        await self.session.flush()
        await self.session.refresh(merged)
        return merged

    async def delete(self, record_id: uuid.UUID) -> bool:
        """Delete a record by primary key.

        Returns:
            ``True`` if the record existed and was deleted, ``False`` if
            no record matched ``record_id``.
        """
        obj = await self.get_by_id(record_id)
        if obj is None:
            return False
        self.session.delete(obj)
        await self.session.flush()
        return True

    async def list(
        self,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ModelT], int]:
        """Return a page of records and the total un-paginated count.

        Args:
            offset: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            A tuple of ``(records, total_count)``.
        """
        count_result = await self.session.execute(
            select(func.count()).select_from(self.model_class)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(self.model_class).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total
