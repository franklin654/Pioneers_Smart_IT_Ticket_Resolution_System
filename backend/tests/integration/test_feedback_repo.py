import pytest

from src.db.models import FeedbackAction, RoutingDecision, TicketSource, TicketStatus
from src.db.repositories.feedback_repo import FeedbackRepository
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository


@pytest.mark.asyncio
async def test_create_and_get_by_resolution_id(db_session) -> None:
    ticket_repo = TicketRepository(db_session)
    resolution_repo = ResolutionRepository(db_session)
    feedback_repo = FeedbackRepository(db_session)

    ticket = await ticket_repo.create(
        title="t",
        description="d",
        original_description="d",
        category=None,
        priority=3,
        status=TicketStatus.AUTO_RESOLVED,
        source=TicketSource.API,
        pii_detected=False,
        content_hash="a" * 64,
    )
    resolution = await resolution_repo.create(
        ticket_id=ticket.id,
        suggested_steps=[{"step_number": 1, "instruction": "Restart service"}],
        routing_decision=RoutingDecision.AUTO_RESOLVED,
    )

    feedback = await feedback_repo.create(
        resolution_id=resolution.id,
        agent_id="agent-1",
        action=FeedbackAction.ACCEPTED,
        modified_resolution=None,
    )

    fetched = await feedback_repo.get_by_resolution_id(resolution.id)
    assert len(fetched) == 1
    assert fetched[0].id == feedback.id
    assert fetched[0].action == FeedbackAction.ACCEPTED
