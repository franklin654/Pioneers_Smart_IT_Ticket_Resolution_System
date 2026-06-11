"""Ingestion pipeline orchestrator and shared data structures.

This module is the public surface of the ``ingestion`` package. It defines:

    - ``IngestionContext``  — mutable state object passed between stages
    - ``IngestionResult``   — immutable result returned to callers
    - ``IngestionPipeline`` — orchestrates all stages
    - ``build_ingestion_pipeline()`` — factory for use in FastAPI endpoints

Stage execution order:
    1. Validate     — TicketValidator (raises ValidationError on failure)
    2. Mask PII     — PIIMasker (never raises; falls back on error)
    3. Deduplicate  — Deduplicator (raises DuplicateTicketError on match)
    4. Persist      — Saves Ticket to DB
    5. Return       — Builds and returns IngestionResult

The pipeline does NOT trigger embedding generation or classification.
Those are async background tasks started by the API layer (Phase 6) after
a successful ingestion.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.exceptions import DuplicateTicketError
from src.core.logging import get_logger
from src.db.models import Ticket, TicketCategory, TicketSource, TicketStatus
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.ingestion.deduplicator import Deduplicator
from src.ingestion.pii_masker import PIIMasker
from src.ingestion.validator import TicketValidator
from src.schemas.ticket import TicketIngestRequest

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


# ── Shared data structures ────────────────────────────────────────────────────


@dataclass
class IngestionContext:
    """Mutable state object that accumulates data as it flows through stages.

    Created from a ``TicketIngestRequest`` at pipeline entry and populated
    by each stage in sequence.  No stage should read fields populated by a
    later stage — the order is enforced by the pipeline orchestrator.

    Attributes:
        raw_title: Original title from the request (unmodified).
        raw_description: Original description from the request (unmodified).
        priority: Ticket priority (1–5).
        category_hint: Optional category provided by the submitter.
        source: Origin channel (API, CSV, WEBHOOK).
        clean_title: Sanitized title (set by Stage 1).
        clean_description: Sanitized description (set by Stage 1).
        masked_description: PII-masked description (set by Stage 2).
        pii_detected: True if Presidio found at least one PII entity (Stage 2).
        pii_entity_types: List of detected entity type strings (Stage 2).
        content_hash: SHA-256 of normalized title + description (Stage 3).
        duplicate_type: ``"exact"`` or ``"near"`` if duplicate; else None (Stage 3).
        existing_ticket_id: Matching ticket UUID string if duplicate (Stage 3).
        ticket_id: DB-assigned UUID after persistence (Stage 4).
        ticket_status: Status written to DB (Stage 4).
    """

    # ── Input (set at entry) ──────────────────────────────────────────────
    raw_title: str
    raw_description: str
    priority: int
    category_hint: TicketCategory | None
    source: TicketSource

    # ── Stage 1: Validator ────────────────────────────────────────────────
    clean_title: str | None = None
    clean_description: str | None = None

    # ── Stage 2: PII Masker ───────────────────────────────────────────────
    masked_description: str | None = None
    pii_detected: bool = False
    pii_entity_types: list[str] = field(default_factory=list)

    # ── Stage 3: Deduplicator ─────────────────────────────────────────────
    content_hash: str | None = None
    duplicate_type: str | None = None
    existing_ticket_id: str | None = None

    # ── Stage 4: Persisted ────────────────────────────────────────────────
    ticket_id: uuid.UUID | None = None
    ticket_status: TicketStatus | None = None


@dataclass(frozen=True)
class IngestionResult:
    """Immutable result returned after a successful ingestion.

    Attributes:
        ticket_id: UUID assigned to the newly created ticket.
        status: Initial ticket status (always ``TicketStatus.NEW``).
        pii_detected: Whether PII was found and masked in the description.
        message: Human-readable summary for API response.
    """

    ticket_id: uuid.UUID
    status: TicketStatus
    pii_detected: bool
    message: str


# ── Pipeline ──────────────────────────────────────────────────────────────────


class IngestionPipeline:
    """Orchestrates the 5-stage ticket ingestion flow.

    All dependencies are injected at construction time to enable testing
    without database or model infrastructure.

    Args:
        validator: Stage 1 — sanitizes and validates field constraints.
        pii_masker: Stage 2 — detects and masks PII entities.
        deduplicator: Stage 3 — checks for exact and near duplicates.
        ticket_repo: Stage 4 — persists the Ticket ORM object.
        settings: Application settings (used for source defaults etc.).
    """

    def __init__(
        self,
        validator: TicketValidator,
        pii_masker: PIIMasker,
        deduplicator: Deduplicator,
        ticket_repo: TicketRepository,
        settings: Settings,
    ) -> None:
        self._validator = validator
        self._pii_masker = pii_masker
        self._deduplicator = deduplicator
        self._ticket_repo = ticket_repo
        self._settings = settings

    async def run(
        self,
        request: TicketIngestRequest,
        source: TicketSource = TicketSource.API,
    ) -> IngestionResult:
        """Execute all ingestion stages for an incoming ticket.

        Args:
            request: Pydantic-validated ingest request from the API layer.
            source: Origin channel; defaults to ``TicketSource.API``.

        Returns:
            :class:`IngestionResult` on success.

        Raises:
            ValidationError: If sanitized fields fail constraints (Stage 1).
            DuplicateTicketError: If the ticket is an exact or near-duplicate
                (Stage 3).
        """
        ctx = IngestionContext(
            raw_title=request.title,
            raw_description=request.description,
            priority=request.priority,
            category_hint=request.category,
            source=source,
        )

        # Stage 1 — Validate
        ctx = self._validator.validate(ctx)

        # Stage 2 — Mask PII (never raises; falls back on error)
        ctx = self._pii_masker.mask(ctx)

        # Stage 3 — Deduplicate
        dedup_result = await self._deduplicator.check(ctx)
        ctx.content_hash = dedup_result.content_hash
        ctx.duplicate_type = dedup_result.duplicate_type
        ctx.existing_ticket_id = dedup_result.existing_ticket_id

        if dedup_result.is_duplicate:
            raise DuplicateTicketError(
                existing_ticket_id=dedup_result.existing_ticket_id or "",
                duplicate_type=dedup_result.duplicate_type or "unknown",
            )

        # Stage 4 — Persist
        ticket = await self._persist(ctx)
        ctx.ticket_id = ticket.id
        ctx.ticket_status = ticket.status

        logger.info(
            "Ticket ingested successfully",
            extra={
                "ticket_id": str(ticket.id),
                "metadata": {
                    "pii_detected": ctx.pii_detected,
                    "source": source.value,
                    "priority": ctx.priority,
                },
            },
        )

        return IngestionResult(
            ticket_id=ticket.id,
            status=ticket.status,
            pii_detected=ctx.pii_detected,
            message="Ticket received and queued for processing.",
        )

    async def _persist(self, ctx: IngestionContext) -> Ticket:
        """Create and save a Ticket ORM object from the final context state.

        Uses the masked description for all stored/indexed text.
        The original description is preserved in ``original_description``
        for audit and compliance purposes.

        Args:
            ctx: Fully populated ingestion context (Stages 1–3 complete).

        Returns:
            The persisted :class:`~src.db.models.Ticket` instance.
        """
        ticket = Ticket(
            title=ctx.clean_title or ctx.raw_title,
            # Store masked text as the primary description for all ML operations
            description=ctx.masked_description or ctx.clean_description or ctx.raw_description,
            # Preserve raw input for audit / compliance
            original_description=ctx.raw_description,
            category=ctx.category_hint,
            priority=ctx.priority,
            status=TicketStatus.NEW,
            pii_detected=ctx.pii_detected,
            pii_entity_types=ctx.pii_entity_types if ctx.pii_entity_types else None,
            content_hash=ctx.content_hash or "",
            source=ctx.source,
        )
        return await self._ticket_repo.create(ticket)


# ── Factory ───────────────────────────────────────────────────────────────────


def build_ingestion_pipeline(
    session: AsyncSession,
    embedding_generator: Any | None = None,
) -> IngestionPipeline:
    """Construct a fully-wired IngestionPipeline.

    Intended for use as a FastAPI dependency factory (Phase 6).  The
    ``embedding_generator`` parameter is optional — when ``None``, the
    deduplicator performs only exact-match checking (no near-duplicate
    detection).  Phase 3 will inject the real EmbeddingGenerator here.

    Args:
        session: Active async database session.
        embedding_generator: Optional embedding model with an
            ``encode_single(text: str) -> list[float]`` method.

    Returns:
        A configured :class:`IngestionPipeline` instance.

    Example (FastAPI)::

        @router.post("/tickets/ingest")
        async def ingest(
            request: TicketIngestRequest,
            db: AsyncSession = Depends(get_db),
        ) -> TicketIngestResponse:
            pipeline = build_ingestion_pipeline(db)
            result = await pipeline.run(request)
            ...
    """
    settings = get_settings()
    ticket_repo = TicketRepository(session)
    embedding_repo = EmbeddingRepository(session)
    deduplicator = Deduplicator(
        ticket_repo=ticket_repo,
        embedding_repo=embedding_repo,
        embedding_generator=embedding_generator,
        settings=settings,
    )
    return IngestionPipeline(
        validator=TicketValidator(),
        pii_masker=PIIMasker(),
        deduplicator=deduplicator,
        ticket_repo=ticket_repo,
        settings=settings,
    )
