"""Repeated-issue detection for the escalation pipeline.

Queries the ticket repository for same-category tickets in a configurable
look-back window.  If recurrences exceed a threshold the resolution is flagged
and an automation suggestion is generated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.logging import get_logger
from src.db.models import TicketCategory

if TYPE_CHECKING:
    from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)


@dataclass
class EscalationContext:
    """Result of a repeated-issue check.

    Attributes:
        is_repeated_issue: ``True`` when recurrence_count ≥ threshold.
        recurrence_count: Number of same-category tickets in the look-back
            window (excluding the current ticket).
        automation_suggestion: Plain-text suggestion when flagged; ``None``
            when not a repeated issue.
    """

    is_repeated_issue: bool
    recurrence_count: int
    automation_suggestion: str | None


class EscalationDetector:
    """Detects recurring ticket patterns and suggests automation opportunities.

    Args:
        ticket_repo: :class:`~src.db.repositories.ticket_repo.TicketRepository`
            used for DB look-ups.
        lookback_days: Window (in days) to search for prior tickets.
            Default: 30.
        recurrence_threshold: Minimum number of same-category tickets (excluding
            the current one) required to flag as a repeated issue.  Default: 3.
    """

    def __init__(
        self,
        ticket_repo: "TicketRepository",
        lookback_days: int = 30,
        recurrence_threshold: int = 3,
    ) -> None:
        self._repo = ticket_repo
        self._lookback_days = lookback_days
        self._recurrence_threshold = recurrence_threshold

    async def check(
        self,
        category: TicketCategory,
        exclude_ticket_id: uuid.UUID,
    ) -> EscalationContext:
        """Check for recurring same-category tickets in the look-back window.

        Args:
            category: The ticket's predicted category.
            exclude_ticket_id: UUID of the current ticket — excluded from the
                count so a ticket never counts itself.

        Returns:
            :class:`EscalationContext` indicating whether this is a repeated
            issue and an optional automation suggestion.
        """
        recent = await self._repo.get_recent_by_category(
            category=category,
            days=self._lookback_days,
        )
        # Exclude the current ticket from the recurrence count
        others = [t for t in recent if t.id != exclude_ticket_id]
        count = len(others)

        is_repeated = count >= self._recurrence_threshold

        suggestion: str | None = None
        if is_repeated:
            suggestion = (
                f"This {category.value} issue has recurred {count} time"
                f"{'s' if count != 1 else ''} in the last {self._lookback_days} days"
                f" — consider creating an automated runbook."
            )

        logger.info(
            "Escalation check complete",
            extra={
                "metadata": {
                    "category": category.value,
                    "recurrence_count": count,
                    "is_repeated_issue": is_repeated,
                    "lookback_days": self._lookback_days,
                }
            },
        )
        return EscalationContext(
            is_repeated_issue=is_repeated,
            recurrence_count=count,
            automation_suggestion=suggestion,
        )
