"""Repository for Classification records."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.db.models import Classification
from src.db.repositories.base_repo import BaseRepository


class ClassificationRepository(BaseRepository[Classification]):
    """CRUD repository for :class:`~src.db.models.Classification`.

    Inherits ``create``, ``get_by_id``, ``update``, ``delete``, and ``list``
    from :class:`BaseRepository`.  Adds a ``get_by_ticket_id`` domain query
    for looking up a ticket's classification result.
    """

    model_class = Classification

    async def get_by_ticket_id(self, ticket_id: uuid.UUID) -> Classification | None:
        """Return the classification for a given ticket, or None if absent.

        Args:
            ticket_id: UUID of the parent ticket.

        Returns:
            The :class:`Classification` row, or ``None``.
        """
        result = await self.session.execute(
            select(Classification).where(Classification.ticket_id == ticket_id)
        )
        return result.scalar_one_or_none()
