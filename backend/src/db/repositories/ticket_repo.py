"""Repository for the Ticket model with domain-specific query methods."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from src.db.models import Ticket, TicketCategory, TicketSource, TicketStatus
from src.db.repositories.base_repo import BaseRepository


@dataclass
class TicketSearchFilters:
    """Value object encapsulating optional filter parameters for ticket list queries.

    All fields are optional — ``None`` means "no filter applied" for that field.
    """

    category: TicketCategory | None = None
    status: TicketStatus | None = None
    priority: int | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None


class TicketRepository(BaseRepository[Ticket]):
    """Repository for :class:`~src.db.models.Ticket` with domain queries.

    Inherits standard CRUD from :class:`BaseRepository`.
    """

    model_class = Ticket

    # ── Static helpers ────────────────────────────────────────────────────

    @staticmethod
    def compute_content_hash(title: str, description: str) -> str:
        """Compute a SHA-256 hex digest over normalized ``title + description``.

        Used for exact-duplicate detection during ingestion.  SHA-256 is
        preferred over MD5 to satisfy security linters (ruff S324) while
        providing deterministic, collision-resistant hashing.  The digest is
        stable across identical inputs regardless of surrounding whitespace.

        Args:
            title: Raw ticket title.
            description: Raw ticket description (pre-PII masking).

        Returns:
            64-character lowercase hex string.
        """
        # Collapse internal whitespace too so "VPN  Down" == "VPN Down"
        norm_title = " ".join(title.split()).lower()
        norm_desc = " ".join(description.split()).lower()
        normalized = f"{norm_title}::{norm_desc}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # ── Domain queries ────────────────────────────────────────────────────

    async def get_by_hash(self, content_hash: str) -> Ticket | None:
        """Look up a ticket by its content hash.

        Args:
            content_hash: SHA-256 hex digest returned by ``compute_content_hash``.

        Returns:
            Matching ``Ticket``, or ``None`` if not found.
        """
        result = await self.session.execute(
            select(Ticket).where(Ticket.content_hash == content_hash)
        )
        return result.scalar_one_or_none()

    async def get_with_relations(self, ticket_id: uuid.UUID) -> Ticket | None:
        """Fetch a ticket with its classification, resolution, and embedding loaded.

        Uses ``selectinload`` to avoid N+1 queries.

        Args:
            ticket_id: UUID of the ticket to fetch.

        Returns:
            ``Ticket`` with child relations populated, or ``None``.
        """
        result = await self.session.execute(
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .options(
                selectinload(Ticket.classification),
                selectinload(Ticket.resolution),
                selectinload(Ticket.embedding),
            )
        )
        return result.scalar_one_or_none()

    async def update_status(
        self, ticket_id: uuid.UUID, new_status: TicketStatus
    ) -> Ticket | None:
        """Transition a ticket to a new status.

        Args:
            ticket_id: UUID of the ticket to update.
            new_status: The target :class:`TicketStatus`.

        Returns:
            The updated ``Ticket``, or ``None`` if the ticket was not found.
        """
        await self.session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(status=new_status)
        )
        await self.session.flush()
        return await self.get_by_id(ticket_id)

    async def search(
        self,
        filters: TicketSearchFilters,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Ticket], int]:
        """Paginated ticket list with optional filtering.

        Args:
            filters: Filter criteria; ``None`` values are ignored.
            offset: Records to skip.
            limit: Maximum records to return.

        Returns:
            Tuple of ``(tickets, total_matching_count)``.
        """
        base_query = select(Ticket)
        count_query = select(func.count()).select_from(Ticket)

        conditions = []
        if filters.category:
            conditions.append(Ticket.category == filters.category)
        if filters.status:
            conditions.append(Ticket.status == filters.status)
        if filters.priority:
            conditions.append(Ticket.priority == filters.priority)
        if filters.from_date:
            conditions.append(Ticket.created_at >= filters.from_date)
        if filters.to_date:
            conditions.append(Ticket.created_at <= filters.to_date)

        if conditions:
            base_query = base_query.where(*conditions)
            count_query = count_query.where(*conditions)

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        result = await self.session.execute(
            base_query.order_by(Ticket.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_by_source(self, source: TicketSource, limit: int = 1000) -> list[Ticket]:
        """Return tickets from a specific source channel, with classification loaded.

        Used by the routing accuracy evaluator to fetch the held-out ServiceNow
        test set (source = TicketSource.WEBHOOK) after pipeline processing.

        Args:
            source: The :class:`TicketSource` enum value to filter on.
            limit: Maximum number of tickets to return.

        Returns:
            List of tickets with their ``classification`` relation populated.
        """
        result = await self.session.execute(
            select(Ticket)
            .where(Ticket.source == source)
            .options(selectinload(Ticket.classification))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent_by_category(
        self, category: TicketCategory, days: int
    ) -> list[Ticket]:
        """Return tickets in a category created within the last ``days`` days.

        Used by the escalation module to detect repeated issues.

        Args:
            category: The ticket category to filter on.
            days: Look-back window in days.

        Returns:
            List of matching tickets ordered by ``created_at`` descending.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self.session.execute(
            select(Ticket)
            .where(Ticket.category == category, Ticket.created_at >= cutoff)
            .order_by(Ticket.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_training_data(self, limit: int = 200_000) -> list[Ticket]:
        """Return labeled tickets for classifier training.

        Excludes held-out test sets (WEBHOOK source) so evaluation data never
        leaks into training. The 200K default cap prevents OOM on large corpora.

        Args:
            limit: Maximum number of tickets to return.

        Returns:
            List of tickets that have a non-null ``category``.
        """
        result = await self.session.execute(
            select(Ticket)
            .where(Ticket.category.is_not(None))
            .where(Ticket.source != TicketSource.WEBHOOK)
            .limit(limit)
        )
        return list(result.scalars().all())
