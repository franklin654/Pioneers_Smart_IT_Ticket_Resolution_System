import pytest

from src.db.models import RoutingDecision, TicketSource, TicketStatus
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository


async def _make_ticket(ticket_repo: TicketRepository, n: int):
    return await ticket_repo.create(
        title=f"Ticket {n}",
        description="desc",
        original_description="desc",
        category=None,
        priority=3,
        status=TicketStatus.AWAITING_REVIEW,
        source=TicketSource.API,
        pii_detected=False,
        content_hash=f"{n:064x}",
    )


@pytest.mark.asyncio
async def test_create_pre_gate_stub_and_fetch(db_session) -> None:
    ticket_repo = TicketRepository(db_session)
    resolution_repo = ResolutionRepository(db_session)
    ticket = await _make_ticket(ticket_repo, 1)

    stub = await resolution_repo.create(
        ticket_id=ticket.id,
        suggested_steps=None,
        routing_decision=RoutingDecision.AWAITING_REVIEW,
        escalation_reason="Low classifier confidence (0.42)",
    )

    fetched = await resolution_repo.get_by_ticket_id(ticket.id)
    assert fetched is not None
    assert fetched.id == stub.id
    assert fetched.suggested_steps is None
    assert fetched.feedback_logs == []


@pytest.mark.asyncio
async def test_delete_by_ticket_id_discards_stub_for_resume(db_session) -> None:
    ticket_repo = TicketRepository(db_session)
    resolution_repo = ResolutionRepository(db_session)
    ticket = await _make_ticket(ticket_repo, 2)
    await resolution_repo.create(
        ticket_id=ticket.id,
        suggested_steps=None,
        routing_decision=RoutingDecision.AWAITING_REVIEW,
        escalation_reason="Multi-domain ticket requires specialist review",
    )

    await resolution_repo.delete_by_ticket_id(ticket.id)

    assert await resolution_repo.get_by_ticket_id(ticket.id) is None


@pytest.mark.asyncio
async def test_delete_by_ticket_id_is_a_no_op_when_nothing_exists(db_session) -> None:
    ticket_repo = TicketRepository(db_session)
    resolution_repo = ResolutionRepository(db_session)
    ticket = await _make_ticket(ticket_repo, 3)

    await resolution_repo.delete_by_ticket_id(ticket.id)  # must not raise

    assert await resolution_repo.get_by_ticket_id(ticket.id) is None
