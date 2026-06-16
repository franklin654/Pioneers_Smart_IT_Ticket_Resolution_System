"""Queries for `feedback_logs` — written by `POST /resolutions/{id}/feedback`
(Phase 6)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.db.models import FeedbackLog
from src.db.repositories.base_repo import BaseRepository


class FeedbackRepository(BaseRepository[FeedbackLog]):
    model = FeedbackLog

    async def get_by_resolution_id(self, resolution_id: uuid.UUID) -> list[FeedbackLog]:
        stmt = select(FeedbackLog).where(FeedbackLog.resolution_id == resolution_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)
