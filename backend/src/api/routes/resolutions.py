"""Resolution feedback endpoint.

Endpoint:
    POST /api/v1/resolutions/{ticket_id}/feedback  — record agent action on a resolution
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from src.api.dependencies import get_resolution_repo
from src.api.middleware.auth import get_current_user
from src.core.exceptions import TicketNotFoundError
from src.db.models import FeedbackLog
from src.db.repositories.resolution_repo import ResolutionRepository
from src.schemas.resolution import FeedbackRequest

router = APIRouter(tags=["resolutions"])


@router.post("/{ticket_id}/feedback", status_code=204)
async def submit_feedback(
    ticket_id: uuid.UUID,
    body: FeedbackRequest,
    repo: ResolutionRepository = Depends(get_resolution_repo),
    user: dict = Depends(get_current_user),
) -> Response:
    """Record an agent's action on a resolution suggestion.

    Actions:
        - ``ACCEPTED``  — agent used the suggestion as-is.
        - ``MODIFIED``  — agent edited the suggestion (``modified_resolution`` required).
        - ``REJECTED``  — agent discarded the suggestion.

    MODIFIED resolutions feed back into the knowledge base in a future
    pipeline run.

    Args:
        ticket_id: UUID of the ticket whose resolution is being reviewed.
        body: Feedback payload containing action and optional modified text.
        repo: Injected resolution repository.
        user: Authenticated user payload (agent identity).

    Returns:
        HTTP 204 No Content on success.

    Raises:
        TicketNotFoundError: 404 — no resolution exists for this ticket yet.
    """
    resolution = await repo.get_by_ticket_id(ticket_id)
    if resolution is None:
        raise TicketNotFoundError(str(ticket_id))

    feedback = FeedbackLog(
        resolution_id=resolution.id,
        agent_id=user.get("sub", "unknown"),
        action=body.action,
        modified_resolution=body.modified_resolution,
    )
    await repo.add_feedback(feedback)
    return Response(status_code=204)
