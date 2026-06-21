"""Queries for `resolutions`. `delete_by_ticket_id` backs
`TicketOrchestrator.resume_after_reclassification` — it discards the
pre-generation-gate stub row before the full pipeline re-runs and writes the
real one (docs/03_BACKEND_DESIGN.md)."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from src.db.models import FeedbackAction, FeedbackLog, Resolution, ResolutionStep
from src.db.repositories.base_repo import BaseRepository


class ResolutionRepository(BaseRepository[Resolution]):
    model = Resolution

    async def get_by_ticket_id(self, ticket_id: uuid.UUID) -> Resolution | None:
        stmt = (
            select(Resolution)
            .where(Resolution.ticket_id == ticket_id)
            .options(selectinload(Resolution.feedback_logs))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_ticket_id(self, ticket_id: uuid.UUID) -> None:
        existing = await self.get_by_ticket_id(ticket_id)
        if existing is not None:
            await self.delete(existing)

    async def update_suggested_steps(
        self,
        resolution_id: uuid.UUID,
        steps: list[ResolutionStep],
    ) -> None:
        stmt = (
            update(Resolution)
            .where(Resolution.id == resolution_id)
            .values(suggested_steps=[s.model_dump() for s in steps])
        )
        await self.session.execute(stmt)

    async def record_feedback(
        self,
        resolution_id: uuid.UUID,
        action: FeedbackAction,
        modified_steps: list[ResolutionStep] | None = None,
    ) -> FeedbackLog:
        log = FeedbackLog(
            resolution_id=resolution_id,
            action=action,
            modified_resolution=(
                [s.model_dump() for s in modified_steps] if modified_steps else None
            ),
        )
        self.session.add(log)
        await self.session.flush()
        return log
