"""The ingestion pipeline: validate → mask → dedup → persist → return.

This is the "service" layer for ticket intake (CLAUDE.md backend §3's
Controller → Service → Repository → Database). The controller (Phase 6) does
nothing but parse the HTTP request into `TicketIngestRequest` and call
`IngestionPipeline.run()`; all business logic lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.db.models import Ticket, TicketSource, TicketStatus
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.ingestion.deduplicator import Deduplicator
from src.ingestion.pii_masker import PIIMasker
from src.ingestion.validator import TicketValidator
from src.schemas.ticket import TicketIngestRequest


@dataclass(frozen=True, slots=True)
class IngestionResult:
    ticket: Ticket
    pii_detected: bool
    pii_entity_types: list[str]


class IngestionPipeline:
    def __init__(
        self,
        validator: TicketValidator,
        pii_masker: PIIMasker,
        deduplicator: Deduplicator,
        ticket_repo: TicketRepository,
    ) -> None:
        self._validator = validator
        self._pii_masker = pii_masker
        self._deduplicator = deduplicator
        self._ticket_repo = ticket_repo

    async def run(
        self, request: TicketIngestRequest, source: TicketSource = TicketSource.API
    ) -> IngestionResult:
        # Stage 1: validate + sanitize. Pydantic already checked shape/length
        # at the HTTP boundary; this catches what it can't (whitespace-only
        # strings, control characters Postgres would reject outright).
        if request.priority < 1 or request.priority > 5:
            # Defense in depth — Pydantic's Field(ge=1, le=5) already rejects
            # this for HTTP callers, but IngestionPipeline has no other caller
            # today and may get one (e.g. a webhook intake) that skips Pydantic.
            raise ValidationError("Priority must be between 1 and 5.", field="priority")
        validated = self._validator.validate(request.title, request.description)

        # Stage 2: PII detection + masking. The masked text is what every
        # downstream ML stage sees; the raw text is kept as `original_description`
        # for audit/compliance only (docs/03_BACKEND_DESIGN.md's PII
        # preservation invariant).
        mask_result = await self._pii_masker.mask(validated.clean_description)

        # Stage 3: dedup. Raises DuplicateTicketError (exact or near) — the
        # caller (Phase 6's route) maps that to 409, nothing is persisted.
        dedup_result = await self._deduplicator.check(
            validated.clean_title, validated.clean_description
        )

        # Stage 4: persist.
        ticket = await self._ticket_repo.create(
            title=validated.clean_title,
            description=mask_result.masked_text,
            original_description=validated.clean_description,
            category=request.category,
            priority=request.priority,
            status=TicketStatus.NEW,
            source=source,
            pii_detected=mask_result.pii_detected,
            content_hash=dedup_result.content_hash,
        )

        # Stage 5: return.
        return IngestionResult(
            ticket=ticket,
            pii_detected=mask_result.pii_detected,
            pii_entity_types=mask_result.entity_types,
        )


def build_ingestion_pipeline(
    ticket_repo: TicketRepository, embedding_repo: EmbeddingRepository, similarity_threshold: float
) -> IngestionPipeline:
    """Wires a real `IngestionPipeline`. `embedding_generator` is omitted —
    near-duplicate detection stays exact-match-only until Phase 3's
    `embedding/generator.py` exists and a caller passes a real generator into
    `Deduplicator` (see `ingestion/deduplicator.py`'s module docstring)."""
    return IngestionPipeline(
        validator=TicketValidator(),
        pii_masker=PIIMasker(),
        deduplicator=Deduplicator(
            ticket_repo=ticket_repo,
            embedding_repo=embedding_repo,
            similarity_threshold=similarity_threshold,
        ),
        ticket_repo=ticket_repo,
    )
