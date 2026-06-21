"""All ticket-table queries. Fetches only the columns/rows it needs and uses
`selectinload` everywhere a relation is touched, to avoid N+1 lazy-loads
(audit fix L2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from src.db.models import Resolution, Ticket, TicketCategory, TicketSource, TicketStatus
from src.db.repositories.base_repo import BaseRepository


@dataclass(frozen=True, slots=True)
class TicketSearchFilters:
    category: TicketCategory | None = None
    status: TicketStatus | None = None
    priority: int | None = None
    q: str | None = None
    offset: int = 0
    limit: int = 50


class TicketRepository(BaseRepository[Ticket]):
    model = Ticket

    async def get_with_relations(self, ticket_id: uuid.UUID) -> Ticket | None:
        stmt = (
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .options(
                selectinload(Ticket.classification),
                selectinload(Ticket.resolution).selectinload(Resolution.feedback_logs),
                selectinload(Ticket.embedding),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_content_hash(self, content_hash: str) -> Ticket | None:
        stmt = select(Ticket).where(Ticket.content_hash == content_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, ticket_id: uuid.UUID, status: TicketStatus) -> None:
        # Direct SQL UPDATE bypasses the identity map to avoid silent no-ops when
        # the ORM object was already loaded (and possibly partially expired) in the
        # same session by an earlier query such as get_with_relations().
        stmt = update(Ticket).where(Ticket.id == ticket_id).values(status=status)
        await self.session.execute(stmt)

    async def update_category(self, ticket_id: uuid.UUID, category: TicketCategory) -> None:
        stmt = update(Ticket).where(Ticket.id == ticket_id).values(category=category)
        await self.session.execute(stmt)

    async def search(self, filters: TicketSearchFilters) -> tuple[list[Ticket], int]:
        conditions = []
        if filters.category is not None:
            conditions.append(Ticket.category == filters.category)
        if filters.status is not None:
            conditions.append(Ticket.status == filters.status)
        if filters.priority is not None:
            conditions.append(Ticket.priority == filters.priority)
        if filters.q:
            pattern = f"%{filters.q}%"
            conditions.append(
                Ticket.title.ilike(pattern) | Ticket.description.ilike(pattern)
            )

        count_stmt = select(func.count()).select_from(Ticket)
        list_stmt = (
            select(Ticket)
            .options(
                selectinload(Ticket.classification),
                selectinload(Ticket.resolution),
            )
            .order_by(Ticket.created_at.desc())
        )
        for condition in conditions:
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)
        list_stmt = list_stmt.offset(filters.offset).limit(filters.limit)

        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(list_stmt)).scalars().all()
        return list(rows), total

    async def get_training_data(self, limit: int = 50_000) -> list[tuple[str, str, TicketCategory]]:
        """(title, description, category) for every labeled CSV-source ticket.

        The trainer must reach the DB only through this method — never via
        `.session.execute()` directly (audit fix H3).
        """
        stmt = (
            select(Ticket.title, Ticket.description, Ticket.category)
            .where(Ticket.source == TicketSource.CSV, Ticket.category.is_not(None))
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(title, description, category) for title, description, category in rows]

    async def get_by_source(
        self, source: TicketSource, offset: int = 0, limit: int = 50_000
    ) -> list[Ticket]:
        stmt = select(Ticket).where(Ticket.source == source).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)

    async def count_recent_by_category(
        self,
        category: TicketCategory,
        since: datetime,
        exclude_ticket_id: uuid.UUID,
        source: TicketSource = TicketSource.API,
    ) -> int:
        """Used by `EscalationDetector` (Phase 5) to flag repeated issues.

        Restricted to `source` (default `API`, i.e. live traffic) so bulk-loaded
        synthetic training/eval data never inflates "repeated issue" detection.
        """
        stmt = select(func.count()).where(
            Ticket.category == category,
            Ticket.created_at >= since,
            Ticket.id != exclude_ticket_id,
            Ticket.source == source,
        )
        return (await self.session.execute(stmt)).scalar_one()
