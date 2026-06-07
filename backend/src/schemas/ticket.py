"""Pydantic v2 schemas for ticket ingestion and retrieval endpoints."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.db.models import TicketCategory, TicketSource, TicketStatus
from src.schemas.classification import ClassificationResponse
from src.schemas.resolution import ResolutionResponse


class TicketIngestRequest(BaseModel):
    """Payload for submitting a new ticket via POST /api/v1/tickets/ingest.

    Attributes:
        title: Short summary of the issue (3–200 characters).
        description: Full description of the problem (10–5000 characters).
        priority: Urgency level where 1 = Critical and 5 = Informational.
        category: Optional category hint; the classifier assigns one
            automatically when omitted.
    """

    title: Annotated[
        str,
        Field(min_length=3, max_length=200, description="Short ticket title"),
    ]
    description: Annotated[
        str,
        Field(min_length=10, max_length=5000, description="Full problem description"),
    ]
    priority: Annotated[
        int,
        Field(ge=1, le=5, description="1 = Critical … 5 = Informational"),
    ]
    category: TicketCategory | None = Field(
        None,
        description="Optional category hint; omit to let the classifier decide",
    )

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_and_normalize_whitespace(cls, v: str) -> str:
        """Collapse runs of whitespace and strip leading/trailing spaces."""
        return " ".join(str(v).split())


class TicketIngestResponse(BaseModel):
    """Response returned after a ticket is successfully ingested.

    Processing (classification, RAG, routing) happens asynchronously.
    Poll GET /api/v1/tickets/{ticket_id} for the final result.
    """

    ticket_id: uuid.UUID
    status: TicketStatus
    message: str


class TicketSummary(BaseModel):
    """Lightweight ticket representation for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    category: TicketCategory | None
    priority: int
    status: TicketStatus
    created_at: datetime


class TicketDetailResponse(BaseModel):
    """Full ticket detail including nested classification and resolution.

    Returned by GET /api/v1/tickets/{ticket_id}.
    ``classification`` and ``resolution`` are ``None`` while the ticket is
    still being processed.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    category: TicketCategory | None
    priority: int
    status: TicketStatus
    source: TicketSource
    pii_detected: bool
    created_at: datetime
    updated_at: datetime
    classification: ClassificationResponse | None = None
    resolution: ResolutionResponse | None = None


class PaginatedTicketsResponse(BaseModel):
    """Paginated wrapper for ticket list responses."""

    items: list[TicketSummary]
    total: int
    offset: int
    limit: int
