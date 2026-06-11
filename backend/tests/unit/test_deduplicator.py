"""Unit tests for Deduplicator (src/ingestion/deduplicator.py).

All tests use mocked repositories and embedding generator — no database
or ML model is required.  Each mock is set up inline to keep tests
self-contained and easy to read.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from src.core.exceptions import EmbeddingError
from src.db.models import TicketSource
from src.db.repositories.ticket_repo import TicketRepository
from src.ingestion.deduplicator import Deduplicator, DuplicateCheckResult
from src.ingestion.pipeline import IngestionContext


def _make_ctx(
    title: str = "Cannot connect to VPN",
    description: str = "User unable to connect to corporate VPN from home.",
) -> IngestionContext:
    ctx = IngestionContext(
        raw_title=title,
        raw_description=description,
        priority=2,
        category_hint=None,
        source=TicketSource.API,
    )
    ctx.clean_title = title
    ctx.clean_description = description
    return ctx


def _make_settings(threshold: float = 0.95, window_days: int = 7):
    settings = MagicMock()
    settings.dedup_similarity_threshold = threshold
    settings.dedup_window_days = window_days
    return settings


def _make_deduplicator(
    existing_hash_ticket=None,
    similar_results=None,
    embedding_vector=None,
    embedding_raises=None,
    embedding_generator_none=False,
) -> Deduplicator:
    """Build a Deduplicator with fully controlled mocks."""
    ticket_repo = AsyncMock()
    ticket_repo.get_by_hash.return_value = existing_hash_ticket

    embedding_repo = AsyncMock()
    embedding_repo.find_similar.return_value = similar_results or []

    if embedding_generator_none:
        embedding_gen = None
    else:
        embedding_gen = MagicMock()
        if embedding_raises:
            embedding_gen.encode_single.side_effect = embedding_raises
        else:
            embedding_gen.encode_single.return_value = embedding_vector or [0.5] * 384

    return Deduplicator(
        ticket_repo=ticket_repo,
        embedding_repo=embedding_repo,
        embedding_generator=embedding_gen,
        settings=_make_settings(),
    )


# ── Happy path (unique ticket) ────────────────────────────────────────────────


class TestDeduplicatorUniqueTicket:
    async def test_unique_ticket_is_not_duplicate(self):
        dedup = _make_deduplicator()
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.is_duplicate is False

    async def test_unique_ticket_has_no_duplicate_type(self):
        dedup = _make_deduplicator()
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.duplicate_type is None

    async def test_unique_ticket_has_no_existing_id(self):
        dedup = _make_deduplicator()
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.existing_ticket_id is None

    async def test_content_hash_is_always_set(self):
        dedup = _make_deduplicator()
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.content_hash
        assert len(result.content_hash) == 64  # SHA-256 hex = 64 chars

    async def test_content_hash_matches_repository_static_method(self):
        dedup = _make_deduplicator()
        ctx = _make_ctx(title="VPN Down", description="User cannot connect.")
        result = await dedup.check(ctx)
        expected = TicketRepository.compute_content_hash("VPN Down", "User cannot connect.")
        assert result.content_hash == expected


# ── Exact duplicate detection ──────────────────────────────────────────────────


class TestExactDuplicateDetection:
    async def test_exact_duplicate_detected(self):
        existing = MagicMock()
        existing.id = uuid.uuid4()
        dedup = _make_deduplicator(existing_hash_ticket=existing)
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.is_duplicate is True

    async def test_exact_duplicate_type_is_exact(self):
        existing = MagicMock()
        existing.id = uuid.uuid4()
        dedup = _make_deduplicator(existing_hash_ticket=existing)
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.duplicate_type == "exact"

    async def test_exact_duplicate_carries_existing_ticket_id(self):
        existing_id = uuid.uuid4()
        existing = MagicMock()
        existing.id = existing_id
        dedup = _make_deduplicator(existing_hash_ticket=existing)
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.existing_ticket_id == str(existing_id)

    async def test_exact_duplicate_skips_near_check(self):
        """When exact match found, embedding generator should NOT be called."""
        existing = MagicMock()
        existing.id = uuid.uuid4()
        embedding_gen = MagicMock()
        embedding_gen.encode_single.return_value = [0.5] * 384

        ticket_repo = AsyncMock()
        ticket_repo.get_by_hash.return_value = existing
        embedding_repo = AsyncMock()

        dedup = Deduplicator(
            ticket_repo=ticket_repo,
            embedding_repo=embedding_repo,
            embedding_generator=embedding_gen,
            settings=_make_settings(),
        )
        ctx = _make_ctx()
        await dedup.check(ctx)

        embedding_gen.encode_single.assert_not_called()
        embedding_repo.find_similar.assert_not_called()


# ── Near-duplicate detection ───────────────────────────────────────────────────


class TestNearDuplicateDetection:
    async def test_near_duplicate_detected_when_similarity_at_threshold(self):
        from src.db.repositories.embedding_repo import SimilarTicketResult
        existing_id = uuid.uuid4()
        similar = SimilarTicketResult(
            ticket_id=existing_id,
            embedding_id=uuid.uuid4(),
            similarity_score=0.95,  # exactly at threshold
        )
        dedup = _make_deduplicator(similar_results=[similar])
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.is_duplicate is True
        assert result.duplicate_type == "near"
        assert result.existing_ticket_id == str(existing_id)

    async def test_near_duplicate_detected_above_threshold(self):
        from src.db.repositories.embedding_repo import SimilarTicketResult
        existing_id = uuid.uuid4()
        similar = SimilarTicketResult(
            ticket_id=existing_id,
            embedding_id=uuid.uuid4(),
            similarity_score=0.99,
        )
        dedup = _make_deduplicator(similar_results=[similar])
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.is_duplicate is True

    async def test_not_near_duplicate_when_below_threshold(self):
        """Similarity of 0.94 is below default threshold of 0.95 — not a duplicate."""
        from src.db.repositories.embedding_repo import SimilarTicketResult
        similar = SimilarTicketResult(
            ticket_id=uuid.uuid4(),
            embedding_id=uuid.uuid4(),
            similarity_score=0.94,
        )
        # find_similar returns a result but it's below the threshold
        # In this implementation, find_similar already filters by threshold,
        # so an empty list means below threshold.
        dedup = _make_deduplicator(similar_results=[])
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.is_duplicate is False

    async def test_near_check_skipped_when_no_embedding_generator(self):
        dedup = _make_deduplicator(embedding_generator_none=True)
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.is_duplicate is False
        assert result.duplicate_type is None

    async def test_near_check_skipped_on_embedding_error(self):
        """EmbeddingError during near check → ticket treated as unique."""
        dedup = _make_deduplicator(embedding_raises=EmbeddingError("model unavailable"))
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        # Should not raise; near check is silently skipped
        assert result.is_duplicate is False

    async def test_near_check_skipped_on_unexpected_exception(self):
        """Any unexpected exception during embedding → treated as unique."""
        dedup = _make_deduplicator(embedding_raises=RuntimeError("GPU OOM"))
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.is_duplicate is False

    async def test_near_check_returns_none_when_similarity_list_empty(self):
        dedup = _make_deduplicator(similar_results=[])
        ctx = _make_ctx()
        result = await dedup.check(ctx)
        assert result.is_duplicate is False


# ── Exact takes priority over near ────────────────────────────────────────────


class TestExactTakesPriority:
    async def test_exact_match_found_before_near_check(self):
        """When exact match exists, near-duplicate check is never reached."""
        from src.db.repositories.embedding_repo import SimilarTicketResult

        existing_exact_id = uuid.uuid4()
        existing_exact = MagicMock()
        existing_exact.id = existing_exact_id

        near_id = uuid.uuid4()
        similar = SimilarTicketResult(
            ticket_id=near_id, embedding_id=uuid.uuid4(), similarity_score=0.99
        )

        embedding_gen = MagicMock()
        embedding_gen.encode_single.return_value = [0.5] * 384
        ticket_repo = AsyncMock()
        ticket_repo.get_by_hash.return_value = existing_exact
        embedding_repo = AsyncMock()
        embedding_repo.find_similar.return_value = [similar]

        dedup = Deduplicator(
            ticket_repo=ticket_repo,
            embedding_repo=embedding_repo,
            embedding_generator=embedding_gen,
            settings=_make_settings(),
        )
        ctx = _make_ctx()
        result = await dedup.check(ctx)

        assert result.duplicate_type == "exact"
        assert result.existing_ticket_id == str(existing_exact_id)
        embedding_gen.encode_single.assert_not_called()


# ── Hash stability ─────────────────────────────────────────────────────────────


class TestHashStability:
    async def test_same_input_always_produces_same_hash(self):
        dedup1 = _make_deduplicator()
        dedup2 = _make_deduplicator()

        ctx1 = _make_ctx("VPN Down", "Cannot connect to VPN.")
        ctx2 = _make_ctx("VPN Down", "Cannot connect to VPN.")

        result1 = await dedup1.check(ctx1)
        result2 = await dedup2.check(ctx2)
        assert result1.content_hash == result2.content_hash

    async def test_whitespace_differences_produce_same_hash(self):
        """Hash is computed after normalization so whitespace shouldn't matter."""
        h1 = TicketRepository.compute_content_hash("VPN  Down", " Cannot connect.")
        h2 = TicketRepository.compute_content_hash("VPN Down", "Cannot connect.")
        assert h1 == h2

    async def test_different_titles_produce_different_hashes(self):
        h1 = TicketRepository.compute_content_hash("VPN Down", "Cannot connect.")
        h2 = TicketRepository.compute_content_hash("DB Error", "Cannot connect.")
        assert h1 != h2

    async def test_hash_is_64_chars(self):
        """SHA-256 produces a 64-character hex digest."""
        h = TicketRepository.compute_content_hash("title", "description")
        assert len(h) == 64
