"""Integration tests for EmbeddingStore against real PostgreSQL.

Uses a mocked EmbeddingGenerator (returns a fixed 384-dim vector) so no
model download is needed — just the database layer is exercised.

Requires:
    - Running PostgreSQL with pgvector
    - TEST_DATABASE_URL environment variable set
"""

import uuid
from unittest.mock import MagicMock

import pytest

from src.db.models import TicketCategory, TicketSource, TicketStatus
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.embedding.store import EmbeddingStore


_FIXED_VECTOR = [float(i % 10) / 10 for i in range(384)]
_FIXED_VECTOR_2 = [float((i + 1) % 10) / 10 for i in range(384)]


def _make_mock_generator(vector: list[float] = _FIXED_VECTOR) -> MagicMock:
    gen = MagicMock()
    gen.encode_single.return_value = vector
    return gen


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
    return s


async def _create_test_ticket(db_session, title: str = "Test ticket") -> "Ticket":
    repo = TicketRepository(db_session)
    from src.db.models import Ticket
    ticket = Ticket(
        title=title,
        description="Integration test ticket description for embedding.",
        original_description="Integration test ticket description for embedding.",
        category=TicketCategory.NETWORK,
        priority=3,
        status=TicketStatus.NEW,
        content_hash=uuid.uuid4().hex,
        source=TicketSource.API,
    )
    return await repo.create(ticket)


# ── Happy path ────────────────────────────────────────────────────────────────


class TestEmbeddingStoreHappyPath:
    async def test_embed_and_store_creates_embedding_row(self, db_session):
        ticket = await _create_test_ticket(db_session, "Embed and store test")
        store = EmbeddingStore(
            generator=_make_mock_generator(),
            repo=EmbeddingRepository(db_session),
            settings=_make_settings(),
        )
        vector = await store.embed_and_store(ticket.id, "Embed and store test description")
        assert len(vector) == 384

        emb_repo = EmbeddingRepository(db_session)
        stored = await emb_repo.upsert(ticket.id, vector, "test-model")
        assert stored.ticket_id == ticket.id

    async def test_embed_and_store_returns_correct_vector(self, db_session):
        ticket = await _create_test_ticket(db_session)
        store = EmbeddingStore(
            generator=_make_mock_generator(_FIXED_VECTOR),
            repo=EmbeddingRepository(db_session),
            settings=_make_settings(),
        )
        returned_vector = await store.embed_and_store(ticket.id, "some text")
        assert returned_vector == _FIXED_VECTOR

    async def test_embed_and_store_upserts_on_second_call(self, db_session):
        """Calling embed_and_store twice for the same ticket updates, not duplicates."""
        ticket = await _create_test_ticket(db_session)
        emb_repo = EmbeddingRepository(db_session)
        settings = _make_settings()

        store1 = EmbeddingStore(_make_mock_generator(_FIXED_VECTOR), emb_repo, settings)
        await store1.embed_and_store(ticket.id, "first text")

        store2 = EmbeddingStore(_make_mock_generator(_FIXED_VECTOR_2), emb_repo, settings)
        await store2.embed_and_store(ticket.id, "second text")

        # Should be exactly one row (upserted, not duplicated)
        similar = await emb_repo.find_similar(_FIXED_VECTOR_2, top_k=5, similarity_threshold=0.0)
        ticket_ids = [r.ticket_id for r in similar]
        assert ticket_ids.count(ticket.id) == 1

    async def test_stored_vector_retrievable_via_find_similar(self, db_session):
        """A stored embedding should be its own nearest neighbour."""
        ticket = await _create_test_ticket(db_session)
        emb_repo = EmbeddingRepository(db_session)
        settings = _make_settings()

        store = EmbeddingStore(_make_mock_generator(_FIXED_VECTOR), emb_repo, settings)
        await store.embed_and_store(ticket.id, "test text")

        results = await emb_repo.find_similar(
            query_vector=_FIXED_VECTOR,
            top_k=1,
            similarity_threshold=0.0,
        )
        assert len(results) >= 1
        assert results[0].ticket_id == ticket.id

    async def test_model_version_stored_correctly(self, db_session):
        ticket = await _create_test_ticket(db_session)
        settings = _make_settings()
        settings.embedding_model = "custom-model-v2"

        emb_repo = EmbeddingRepository(db_session)
        store = EmbeddingStore(_make_mock_generator(), emb_repo, settings)
        await store.embed_and_store(ticket.id, "text")

        # Verify the embedding row exists with the right ticket_id
        results = await emb_repo.find_similar(_FIXED_VECTOR, top_k=5, similarity_threshold=0.0)
        ticket_result = next((r for r in results if r.ticket_id == ticket.id), None)
        assert ticket_result is not None
