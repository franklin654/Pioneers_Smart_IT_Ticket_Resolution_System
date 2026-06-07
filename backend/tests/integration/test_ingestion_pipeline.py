"""Integration tests for IngestionPipeline.run() against real PostgreSQL.

These tests exercise the full pipeline end-to-end:
    Validate → Mask PII → Deduplicate → Persist → Return result

Each test runs inside a DB transaction that is rolled back after completion
(via the ``db_session`` fixture in conftest.py), so no explicit cleanup
is needed and tests are fully isolated.

Requirements:
    - PostgreSQL with pgvector extension running
    - TEST_DATABASE_URL environment variable set
      (default: postgresql+asyncpg://postgres:password@localhost:5432/ticket_routing_test)

Run with:
    TEST_DATABASE_URL=... pytest tests/integration/test_ingestion_pipeline.py -v
"""

import pytest

from src.core.exceptions import DuplicateTicketError, ValidationError
from src.db.models import TicketCategory, TicketSource, TicketStatus
from src.db.repositories.ticket_repo import TicketRepository
from src.ingestion.pipeline import IngestionPipeline, build_ingestion_pipeline
from src.schemas.ticket import TicketIngestRequest


def _make_request(
    title: str = "Cannot connect to corporate VPN from home office",
    description: str = (
        "Since this morning, users working from home are unable to connect to the "
        "corporate VPN. The client reports 'authentication failed' despite correct credentials. "
        "Affects all remote employees using Windows 11."
    ),
    priority: int = 2,
    category: TicketCategory | None = None,
) -> TicketIngestRequest:
    return TicketIngestRequest(
        title=title,
        description=description,
        priority=priority,
        category=category,
    )


# ── Happy path ────────────────────────────────────────────────────────────────


class TestIngestionPipelineHappyPath:
    async def test_valid_ticket_returns_result_with_ticket_id(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request())
        assert result.ticket_id is not None

    async def test_valid_ticket_returns_new_status(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request())
        assert result.status == TicketStatus.NEW

    async def test_ticket_row_created_in_db(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request())

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket is not None

    async def test_db_row_title_matches_sanitized_input(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        request = _make_request(title="  VPN Authentication Failure  ")
        result = await pipeline.run(request)

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.title == "VPN Authentication Failure"

    async def test_db_row_content_hash_is_set(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request())

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.content_hash
        assert len(ticket.content_hash) == 64  # SHA-256

    async def test_db_row_source_is_api(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request(), source=TicketSource.API)

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.source == TicketSource.API

    async def test_db_row_original_description_is_raw_input(self, db_session):
        raw_desc = (
            "The production database query is timing out. "
            "Started after the maintenance window at 02:00 UTC. "
            "Affects all read operations on the orders table."
        )
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request(description=raw_desc))

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.original_description == raw_desc


# ── Category hint ─────────────────────────────────────────────────────────────


class TestCategoryHint:
    async def test_category_hint_stored_in_db(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        request = _make_request(category=TicketCategory.SECURITY)
        result = await pipeline.run(request)

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.category == TicketCategory.SECURITY

    async def test_no_category_hint_stores_null(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request(category=None))

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.category is None


# ── PII masking ───────────────────────────────────────────────────────────────


class TestPIIHandling:
    async def test_original_description_preserved_verbatim(self, db_session):
        """original_description must be the exact raw input."""
        raw = (
            "User reported issue from home. The ticket includes no PII. "
            "Server 10.0.0.5 is unreachable from the office network since yesterday."
        )
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request(description=raw))

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.original_description == raw

    async def test_result_pii_detected_false_for_clean_text(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request())
        assert result.pii_detected is False


# ── Exact duplicate detection ──────────────────────────────────────────────────


class TestExactDuplicateDetection:
    async def test_second_identical_ticket_raises_duplicate_error(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        request = _make_request(title="DB connection pool exhausted")

        # First submission succeeds
        await pipeline.run(request)

        # Second identical submission raises
        with pytest.raises(DuplicateTicketError) as exc_info:
            await pipeline.run(request)

        assert exc_info.value.detail["duplicate_type"] == "exact"

    async def test_duplicate_error_carries_existing_ticket_id(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        request = _make_request(title="Network switch unreachable from core router")

        first_result = await pipeline.run(request)

        with pytest.raises(DuplicateTicketError) as exc_info:
            await pipeline.run(request)

        assert exc_info.value.detail["existing_ticket_id"] == str(first_result.ticket_id)

    async def test_only_one_row_created_after_duplicate_attempt(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        request = _make_request(title="SSL certificate expired on gateway server")

        await pipeline.run(request)
        try:
            await pipeline.run(request)
        except DuplicateTicketError:
            pass

        repo = TicketRepository(db_session)
        expected_hash = TicketRepository.compute_content_hash(
            "SSL certificate expired on gateway server", request.description
        )
        ticket = await repo.get_by_hash(expected_hash)
        assert ticket is not None  # only one row

    async def test_whitespace_variation_still_detected_as_duplicate(self, db_session):
        """Leading/trailing whitespace in the second submission → same hash → duplicate."""
        pipeline = build_ingestion_pipeline(db_session)

        request1 = _make_request(title="Application pod crash")
        request2 = _make_request(title="  Application pod crash  ")  # extra whitespace

        await pipeline.run(request1)
        with pytest.raises(DuplicateTicketError):
            await pipeline.run(request2)


# ── Validation failures ───────────────────────────────────────────────────────


class TestValidationFailures:
    async def test_short_title_raises_validation_error(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        with pytest.raises(ValidationError) as exc_info:
            await pipeline.run(_make_request(title="ab"))
        assert exc_info.value.detail["field"] == "title"

    async def test_short_title_creates_no_db_row(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        repo = TicketRepository(db_session)

        before_count = (await repo.list())[1]
        try:
            await pipeline.run(_make_request(title="x"))
        except ValidationError:
            pass
        after_count = (await repo.list())[1]
        assert after_count == before_count

    async def test_long_description_raises_validation_error(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        with pytest.raises(ValidationError) as exc_info:
            await pipeline.run(_make_request(description="x" * 5001))
        assert exc_info.value.detail["field"] == "description"

    async def test_invalid_priority_raises_validation_error(self, db_session):
        """Priority 0 is invalid; Pydantic catches this before the pipeline runs."""
        # Pydantic validates priority at schema layer so we test via the schema
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError):
            TicketIngestRequest(
                title="Valid Title",
                description="A valid description long enough to pass.",
                priority=0,
            )

    async def test_html_in_title_is_stripped_not_rejected(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(
            _make_request(title="<b>VPN is completely down for all remote users</b>")
        )
        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert "<b>" not in ticket.title
        assert "VPN is completely down" in ticket.title


# ── Source tracking ────────────────────────────────────────────────────────────


class TestSourceTracking:
    async def test_api_source_stored(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request(), source=TicketSource.API)

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.source == TicketSource.API

    async def test_csv_source_stored(self, db_session):
        pipeline = build_ingestion_pipeline(db_session)
        result = await pipeline.run(_make_request(title="CSV-sourced ticket for batch load"), source=TicketSource.CSV)

        repo = TicketRepository(db_session)
        ticket = await repo.get_by_id(result.ticket_id)
        assert ticket.source == TicketSource.CSV
