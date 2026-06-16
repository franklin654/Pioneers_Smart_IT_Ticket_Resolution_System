"""Queries for `classifications` — one row per ticket, written once per
pipeline pass (and again on reclassification resume)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.db.models import Classification
from src.db.repositories.base_repo import BaseRepository


class ClassificationRepository(BaseRepository[Classification]):
    model = Classification

    async def get_by_ticket_id(self, ticket_id: uuid.UUID) -> Classification | None:
        stmt = select(Classification).where(Classification.ticket_id == ticket_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_ticket_id(self, ticket_id: uuid.UUID) -> None:
        existing = await self.get_by_ticket_id(ticket_id)
        if existing is not None:
            await self.delete(existing)
