"""Unit tests for EscalationDetector (src/routing/escalation.py).

Mocks TicketRepository — no DB required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.models import TicketCategory
from src.routing.escalation import EscalationContext, EscalationDetector


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ticket(ticket_id: uuid.UUID | None = None) -> MagicMock:
    t = MagicMock()
    t.id = ticket_id or uuid.uuid4()
    return t


def _make_detector(
    tickets: list[MagicMock],
    lookback_days: int = 30,
    recurrence_threshold: int = 3,
) -> EscalationDetector:
    repo = AsyncMock()
    repo.get_recent_by_category.return_value = tickets
    return EscalationDetector(
        ticket_repo=repo,
        lookback_days=lookback_days,
        recurrence_threshold=recurrence_threshold,
    )


# ── Not a repeated issue ──────────────────────────────────────────────────────


class TestNotRepeatedIssue:
    async def test_below_threshold_not_flagged(self):
        current_id = uuid.uuid4()
        tickets = [_make_ticket() for _ in range(2)]  # 2 < threshold(3)
        detector = _make_detector(tickets, recurrence_threshold=3)
        result = await detector.check(TicketCategory.NETWORK, current_id)
        assert result.is_repeated_issue is False

    async def test_zero_recurrences_not_flagged(self):
        current_id = uuid.uuid4()
        detector = _make_detector([], recurrence_threshold=3)
        result = await detector.check(TicketCategory.INFRASTRUCTURE, current_id)
        assert result.is_repeated_issue is False
        assert result.recurrence_count == 0

    async def test_no_suggestion_when_not_repeated(self):
        detector = _make_detector([_make_ticket()], recurrence_threshold=3)
        result = await detector.check(TicketCategory.DATABASE, uuid.uuid4())
        assert result.automation_suggestion is None


# ── Repeated issue ────────────────────────────────────────────────────────────


class TestRepeatedIssue:
    async def test_at_threshold_flagged(self):
        current_id = uuid.uuid4()
        tickets = [_make_ticket() for _ in range(3)]  # 3 == threshold
        detector = _make_detector(tickets, recurrence_threshold=3)
        result = await detector.check(TicketCategory.NETWORK, current_id)
        assert result.is_repeated_issue is True

    async def test_above_threshold_flagged(self):
        current_id = uuid.uuid4()
        tickets = [_make_ticket() for _ in range(7)]
        detector = _make_detector(tickets, recurrence_threshold=3)
        result = await detector.check(TicketCategory.SECURITY, current_id)
        assert result.is_repeated_issue is True
        assert result.recurrence_count == 7

    async def test_suggestion_contains_category_name(self):
        detector = _make_detector([_make_ticket() for _ in range(5)], recurrence_threshold=3)
        result = await detector.check(TicketCategory.DATABASE, uuid.uuid4())
        assert "database" in result.automation_suggestion.lower()

    async def test_suggestion_contains_recurrence_count(self):
        detector = _make_detector([_make_ticket() for _ in range(5)], recurrence_threshold=3)
        result = await detector.check(TicketCategory.NETWORK, uuid.uuid4())
        assert "5" in result.automation_suggestion


# ── Current ticket exclusion ──────────────────────────────────────────────────


class TestTicketExclusion:
    async def test_current_ticket_excluded_from_count(self):
        current_id = uuid.uuid4()
        # repo returns 3 tickets: 2 others + 1 current
        tickets = [_make_ticket(), _make_ticket(), _make_ticket(current_id)]
        detector = _make_detector(tickets, recurrence_threshold=3)
        result = await detector.check(TicketCategory.NETWORK, current_id)
        # Only 2 others → below threshold(3)
        assert result.recurrence_count == 2
        assert result.is_repeated_issue is False

    async def test_recurrence_count_excludes_self(self):
        current_id = uuid.uuid4()
        tickets = [_make_ticket(current_id), _make_ticket(), _make_ticket(), _make_ticket()]
        detector = _make_detector(tickets, recurrence_threshold=3)
        result = await detector.check(TicketCategory.APPLICATION, current_id)
        assert result.recurrence_count == 3  # 4 total - 1 self = 3


# ── Lookback days forwarded to repo ──────────────────────────────────────────


class TestLookbackDays:
    async def test_lookback_days_passed_to_repo(self):
        repo = AsyncMock()
        repo.get_recent_by_category.return_value = []
        detector = EscalationDetector(ticket_repo=repo, lookback_days=14, recurrence_threshold=2)
        await detector.check(TicketCategory.NETWORK, uuid.uuid4())
        repo.get_recent_by_category.assert_called_once_with(
            category=TicketCategory.NETWORK,
            days=14,
        )
