import pytest

from src.db.models import (
    ClassificationMethod,
    ConfidenceLevel,
    TicketCategory,
    TicketSource,
    TicketStatus,
)
from src.db.repositories.classification_repo import ClassificationRepository
from src.db.repositories.ticket_repo import TicketRepository


async def _make_ticket(ticket_repo: TicketRepository, n: int):
    return await ticket_repo.create(
        title=f"Ticket {n}",
        description="desc",
        original_description="desc",
        category=None,
        priority=3,
        status=TicketStatus.CLASSIFYING,
        source=TicketSource.API,
        pii_detected=False,
        content_hash=f"{n:064x}",
    )


@pytest.mark.asyncio
async def test_create_and_get_by_ticket_id(db_session) -> None:
    ticket_repo = TicketRepository(db_session)
    classification_repo = ClassificationRepository(db_session)
    ticket = await _make_ticket(ticket_repo, 1)

    created = await classification_repo.create(
        ticket_id=ticket.id,
        predicted_category=TicketCategory.DATABASE,
        confidence=0.91,
        confidence_level=ConfidenceLevel.HIGH,
        top_categories=[{"category": "database", "probability": 0.91}],
        is_multi_domain=False,
        classification_method=ClassificationMethod.MODEL,
    )

    fetched = await classification_repo.get_by_ticket_id(ticket.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.confidence_level == ConfidenceLevel.HIGH


@pytest.mark.asyncio
async def test_get_by_ticket_id_returns_none_when_absent(db_session) -> None:
    ticket_repo = TicketRepository(db_session)
    classification_repo = ClassificationRepository(db_session)
    ticket = await _make_ticket(ticket_repo, 2)

    assert await classification_repo.get_by_ticket_id(ticket.id) is None


@pytest.mark.asyncio
async def test_delete_by_ticket_id_used_on_reclassification_resume(db_session) -> None:
    """`resume_after_reclassification` (Phase 5) discards the stale low-confidence
    classification before the resumed pipeline writes a fresh one."""
    ticket_repo = TicketRepository(db_session)
    classification_repo = ClassificationRepository(db_session)
    ticket = await _make_ticket(ticket_repo, 3)
    await classification_repo.create(
        ticket_id=ticket.id,
        predicted_category=TicketCategory.NETWORK,
        confidence=0.4,
        confidence_level=ConfidenceLevel.LOW,
        top_categories=[],
        is_multi_domain=False,
        classification_method=ClassificationMethod.MODEL,
    )

    await classification_repo.delete_by_ticket_id(ticket.id)

    assert await classification_repo.get_by_ticket_id(ticket.id) is None
