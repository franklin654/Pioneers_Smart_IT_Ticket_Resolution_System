"""Repository for Resolution and FeedbackLog models."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.models import FeedbackLog, Resolution
from src.db.repositories.base_repo import BaseRepository


class ResolutionRepository(BaseRepository[Resolution]):
    """Repository for :class:`~src.db.models.Resolution`.

    Provides look-ups by ticket ID and eager-loading of associated
    :class:`~src.db.models.FeedbackLog` records.
    """

    model_class = Resolution

    async def get_by_ticket_id(self, ticket_id: uuid.UUID) -> Resolution | None:
        """Fetch the resolution for a given ticket, including feedback logs.

        Args:
            ticket_id: UUID of the parent ticket.

        Returns:
            :class:`Resolution` with ``feedback_logs`` eagerly loaded,
            or ``None`` if no resolution exists yet.
        """
        result = await self.session.execute(
            select(Resolution)
            .where(Resolution.ticket_id == ticket_id)
            .options(selectinload(Resolution.feedback_logs))
        )
        return result.scalar_one_or_none()

    async def get_with_feedback(self, resolution_id: uuid.UUID) -> Resolution | None:
        """Fetch a resolution by its own ID, with feedback logs loaded.

        Args:
            resolution_id: UUID of the resolution record.

        Returns:
            :class:`Resolution` with ``feedback_logs`` eagerly loaded,
            or ``None`` if not found.
        """
        result = await self.session.execute(
            select(Resolution)
            .where(Resolution.id == resolution_id)
            .options(selectinload(Resolution.feedback_logs))
        )
        return result.scalar_one_or_none()

    async def get_all_with_quality_scores(self, limit: int = 5000) -> list[Resolution]:
        """Return all Resolution rows where llm_quality_score is not NULL.

        Args:
            limit: Maximum number of rows to fetch.

        Returns:
            List of :class:`Resolution` instances that have been scored.
        """
        result = await self.session.execute(
            select(Resolution)
            .where(Resolution.llm_quality_score.is_not(None))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_feedback(self, feedback: FeedbackLog) -> FeedbackLog:
        """Persist a new feedback log entry.

        Args:
            feedback: :class:`FeedbackLog` instance to insert.

        Returns:
            The persisted instance with DB-generated defaults populated.
        """
        self.session.add(feedback)
        await self.session.flush()
        await self.session.refresh(feedback)
        return feedback
