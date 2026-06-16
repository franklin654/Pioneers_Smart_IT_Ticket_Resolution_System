"""Resolution routes: submit feedback on a resolved ticket."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.api.middleware.auth import CurrentUser
from src.api.middleware.rate_limiter import rate_limit
from src.db.database import session_scope
from src.db.models import TicketStatus
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.schemas.resolution import FeedbackRequest

router = APIRouter(
    prefix="/resolutions",
    tags=["resolutions"],
    dependencies=[Depends(rate_limit)],
)

_TERMINAL_STATUSES = {
    TicketStatus.AUTO_RESOLVED,
    TicketStatus.ASSIGNED,
    TicketStatus.ESCALATED,
}


@router.post("/{ticket_id}/feedback", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def submit_feedback(
    ticket_id: uuid.UUID,
    body: FeedbackRequest,
    _: CurrentUser,
) -> Response:
    async with session_scope() as session:
        ticket_repo = TicketRepository(session)
        resolution_repo = ResolutionRepository(session)

        ticket = await ticket_repo.get_with_relations(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="Ticket not found.")

        if ticket.status not in _TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Feedback can only be submitted on resolved tickets "
                    f"(status={ticket.status.value})."
                ),
            )

        if ticket.resolution is None:
            raise HTTPException(status_code=404, detail="No resolution found for this ticket.")

        await resolution_repo.record_feedback(
            resolution_id=ticket.resolution.id,
            action=body.action,
            modified_steps=body.modified_resolution,
        )

        if body.action == "accepted":
            await ticket_repo.update_status(ticket_id, TicketStatus.AUTO_RESOLVED)
        elif body.action == "modified":
            await ticket_repo.update_status(ticket_id, TicketStatus.AUTO_RESOLVED)
        elif body.action == "rejected":
            await ticket_repo.update_status(ticket_id, TicketStatus.ESCALATED)

        await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
