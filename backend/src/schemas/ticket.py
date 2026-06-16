"""Ticket request/response schemas. Declarative boundary validation
(CLAUDE.md backend §5) — field constraints live here, not as hand-rolled
`if` chains in the controller or the ingestion pipeline.

Only `TicketIngestRequest` is needed for Phase 2 (ingestion). The full
response shapes (`TicketDetailResponse`, `TicketSummary`,
`PaginatedTicketsResponse`, ...) are added in Phase 6 once the API layer
exists to use them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.db.models import TicketCategory


class TicketIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown fields — audit mass-assignment risk

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10_000)
    priority: int = Field(default=3, ge=1, le=5)
    category: TicketCategory | None = None
