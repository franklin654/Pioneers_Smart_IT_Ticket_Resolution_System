import pytest

from src.core.exceptions import DuplicateTicketError, ValidationError
from src.db.models import TicketSource, TicketStatus
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.ingestion.deduplicator import Deduplicator
from src.ingestion.pii_masker import PIIMasker
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.validator import TicketValidator
from src.schemas.ticket import TicketIngestRequest


def _build_pipeline(
    db_session, pii_masker: PIIMasker, similarity_threshold: float = 0.95
) -> IngestionPipeline:
    ticket_repo = TicketRepository(db_session)
    embedding_repo = EmbeddingRepository(db_session)
    return IngestionPipeline(
        validator=TicketValidator(),
        pii_masker=pii_masker,
        deduplicator=Deduplicator(ticket_repo, embedding_repo, similarity_threshold),
        ticket_repo=ticket_repo,
    )


@pytest.mark.asyncio
async def test_run_masks_pii_and_keeps_original_text_for_audit(db_session, pii_masker) -> None:
    pipeline = _build_pipeline(db_session, pii_masker)
    request = TicketIngestRequest(
        title="VPN issue", description="Contact jane.doe@example.com about VPN access."
    )

    result = await pipeline.run(request)

    assert result.pii_detected is True
    assert "EMAIL_ADDRESS" in result.pii_entity_types
    assert result.ticket.status == TicketStatus.NEW
    assert result.ticket.source == TicketSource.API
    assert "jane.doe@example.com" not in result.ticket.description
    assert result.ticket.original_description == "Contact jane.doe@example.com about VPN access."


@pytest.mark.asyncio
async def test_run_with_no_pii_leaves_description_unchanged(db_session, pii_masker) -> None:
    pipeline = _build_pipeline(db_session, pii_masker)
    request = TicketIngestRequest(
        title="Disk full", description="The /var partition is at 98% capacity."
    )

    result = await pipeline.run(request)

    assert result.pii_detected is False
    assert result.ticket.description == "The /var partition is at 98% capacity."


@pytest.mark.asyncio
async def test_run_backfills_category_when_caller_supplies_one(db_session, pii_masker) -> None:
    from src.db.models import TicketCategory

    pipeline = _build_pipeline(db_session, pii_masker)
    request = TicketIngestRequest(
        title="Locked out",
        description="Can't log into the VPN portal.",
        category=TicketCategory.ACCESS_MANAGEMENT,
    )

    result = await pipeline.run(request)

    assert result.ticket.category == TicketCategory.ACCESS_MANAGEMENT


@pytest.mark.asyncio
async def test_run_raises_on_exact_duplicate_and_persists_nothing_twice(
    db_session, pii_masker
) -> None:
    pipeline = _build_pipeline(db_session, pii_masker)
    request = TicketIngestRequest(title="Duplicate ticket", description="Same content every time.")

    first = await pipeline.run(request)

    with pytest.raises(DuplicateTicketError) as exc_info:
        await pipeline.run(request)

    assert exc_info.value.details[0]["duplicate_type"] == "exact"
    assert exc_info.value.details[0]["existing_ticket_id"] == str(first.ticket.id)


@pytest.mark.asyncio
async def test_run_rejects_whitespace_only_title_before_persisting(db_session, pii_masker) -> None:
    """Pydantic's `min_length=1` lets a whitespace-only string through —
    TicketValidator is what actually catches this."""
    pipeline = _build_pipeline(db_session, pii_masker)
    request = TicketIngestRequest(title="   ", description="A perfectly valid description.")

    with pytest.raises(ValidationError):
        await pipeline.run(request)
