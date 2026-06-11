"""Ticket REST endpoints.

Endpoints:
    POST /api/v1/tickets/ingest        — ingest a new ticket (202, async processing)
    GET  /api/v1/tickets/{ticket_id}   — fetch ticket detail with classification + resolution
    GET  /api/v1/tickets/             — paginated list with optional filters
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_ingestion_pipeline, get_ticket_repo, run_orchestrator_background
from src.db.database import get_db
from src.api.middleware.auth import get_current_user
from src.monitoring.metrics import TICKETS_INGESTED_TOTAL
from src.core.exceptions import TicketNotFoundError
from src.db.models import TicketCategory, TicketStatus
from src.db.repositories.ticket_repo import TicketRepository, TicketSearchFilters
from src.ingestion.pipeline import IngestionPipeline
from src.schemas.ticket import (
    PaginatedTicketsResponse,
    TicketDetailResponse,
    TicketIngestRequest,
    TicketIngestResponse,
    TicketSummary,
)

router = APIRouter(tags=["tickets"])


@router.post("/ingest", response_model=TicketIngestResponse, status_code=202)
async def ingest_ticket(
    request: TicketIngestRequest,
    background_tasks: BackgroundTasks,
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> TicketIngestResponse:
    """Ingest a new support ticket and queue it for async AI processing.

    The ticket is validated, PII-masked, deduplicated, and persisted
    synchronously.  Classification, RAG, evaluation, and routing run in a
    background task — poll ``GET /tickets/{ticket_id}`` for the result.

    Args:
        request: Validated ticket payload.
        background_tasks: FastAPI background task runner.
        pipeline: Injected ingestion pipeline.
        db: Shared DB session — committed before background task so the
            background orchestrator can see the newly inserted ticket.

    Returns:
        :class:`TicketIngestResponse` with ``ticket_id`` and initial status.

    Raises:
        ValidationError: 400 — field constraints violated.
        DuplicateTicketError: 409 — exact or near-duplicate detected.
    """
    result = await pipeline.run(request)
    # Commit now: FastAPI's get_db teardown runs AFTER background tasks execute
    # (it exits the outer AsyncExitStack after response() completes), so the
    # background orchestrator would see an uncommitted ticket without this.
    await db.commit()
    TICKETS_INGESTED_TOTAL.labels(source="api", category="unknown").inc()
    background_tasks.add_task(run_orchestrator_background, result.ticket_id)
    return TicketIngestResponse(
        ticket_id=result.ticket_id,
        status=result.status,
        message=result.message,
    )


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    repo: TicketRepository = Depends(get_ticket_repo),
) -> TicketDetailResponse:
    """Fetch full ticket detail including classification and resolution.

    ``classification`` and ``resolution`` fields are ``null`` while the
    ticket is still being processed.

    Args:
        ticket_id: UUID of the ticket to retrieve.
        repo: Injected ticket repository.

    Returns:
        :class:`TicketDetailResponse` with nested classification and resolution.

    Raises:
        TicketNotFoundError: 404 — ticket does not exist.
    """
    ticket = await repo.get_with_relations(ticket_id)
    if ticket is None:
        raise TicketNotFoundError(str(ticket_id))
    return TicketDetailResponse.model_validate(ticket)


@router.get("/", response_model=PaginatedTicketsResponse)
async def list_tickets(
    category: TicketCategory | None = Query(None, description="Filter by category"),
    status: TicketStatus | None = Query(None, description="Filter by status"),
    priority: int | None = Query(None, ge=1, le=5, description="Filter by priority"),
    offset: int = Query(0, ge=0, description="Records to skip"),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    repo: TicketRepository = Depends(get_ticket_repo),
) -> PaginatedTicketsResponse:
    """List tickets with optional filtering and pagination.

    Args:
        category: Optional category filter.
        status: Optional status filter.
        priority: Optional priority filter (1–5).
        offset: Pagination offset.
        limit: Maximum items per page (max 200).
        repo: Injected ticket repository.

    Returns:
        :class:`PaginatedTicketsResponse` with items, total, offset, and limit.
    """
    filters = TicketSearchFilters(category=category, status=status, priority=priority)
    tickets, total = await repo.search(filters, offset=offset, limit=limit)
    return PaginatedTicketsResponse(
        items=[TicketSummary.model_validate(t) for t in tickets],
        total=total,
        offset=offset,
        limit=limit,
    )
