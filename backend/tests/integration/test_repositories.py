"""Integration tests for all repository classes against a real PostgreSQL database.

Requires a running PostgreSQL instance with pgvector.  Set the
TEST_DATABASE_URL environment variable to point at a dedicated test DB.

Each test runs inside a transaction that is rolled back on completion
(see ``db_session`` fixture in conftest.py), so tests are isolated and
the database stays clean without truncation between runs.
"""

import uuid

import pytest

from src.db.models import (
    FeedbackLog,
    KnowledgeBaseEntry,
    Resolution,
    RoutingDecision,
    Ticket,
    TicketCategory,
    TicketSource,
    TicketStatus,
)
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository, TicketSearchFilters


# ── TicketRepository ──────────────────────────────────────────────────────────


class TestTicketRepository:
    async def test_create_and_get_by_id(self, db_session, sample_ticket):
        repo = TicketRepository(db_session)
        created = await repo.create(sample_ticket)

        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.title == sample_ticket.title
        assert fetched.id == created.id

    async def test_get_by_id_returns_none_for_unknown(self, db_session):
        repo = TicketRepository(db_session)
        result = await repo.get_by_id(uuid.uuid4())
        assert result is None

    async def test_get_by_hash_returns_correct_ticket(self, db_session, sample_ticket):
        repo = TicketRepository(db_session)
        created = await repo.create(sample_ticket)

        found = await repo.get_by_hash(sample_ticket.content_hash)
        assert found is not None
        assert found.id == created.id

    async def test_get_by_hash_returns_none_for_unknown_hash(self, db_session):
        repo = TicketRepository(db_session)
        result = await repo.get_by_hash("nonexistent_hash_value")
        assert result is None

    async def test_update_status_changes_status(self, db_session, sample_ticket):
        repo = TicketRepository(db_session)
        created = await repo.create(sample_ticket)

        updated = await repo.update_status(created.id, TicketStatus.CLASSIFIED)
        assert updated is not None
        assert updated.status == TicketStatus.CLASSIFIED

    async def test_update_status_returns_none_for_unknown(self, db_session):
        repo = TicketRepository(db_session)
        result = await repo.update_status(uuid.uuid4(), TicketStatus.CLASSIFIED)
        assert result is None

    async def test_delete_existing_returns_true(self, db_session, sample_ticket):
        repo = TicketRepository(db_session)
        created = await repo.create(sample_ticket)

        deleted = await repo.delete(created.id)
        assert deleted is True
        assert await repo.get_by_id(created.id) is None

    async def test_delete_nonexistent_returns_false(self, db_session):
        repo = TicketRepository(db_session)
        result = await repo.delete(uuid.uuid4())
        assert result is False

    async def test_list_returns_created_ticket(self, db_session, sample_ticket):
        repo = TicketRepository(db_session)
        created = await repo.create(sample_ticket)

        tickets, total = await repo.list(offset=0, limit=100)
        ticket_ids = [t.id for t in tickets]
        assert created.id in ticket_ids
        assert total >= 1

    async def test_search_filters_by_category(self, db_session, sample_ticket):
        repo = TicketRepository(db_session)
        await repo.create(sample_ticket)  # category=NETWORK

        filters = TicketSearchFilters(category=TicketCategory.NETWORK)
        results, total = await repo.search(filters)
        assert total >= 1
        assert all(t.category == TicketCategory.NETWORK for t in results)

    async def test_search_filters_by_status(self, db_session, sample_ticket):
        repo = TicketRepository(db_session)
        await repo.create(sample_ticket)  # status=NEW

        filters = TicketSearchFilters(status=TicketStatus.NEW)
        results, total = await repo.search(filters)
        assert total >= 1
        assert all(t.status == TicketStatus.NEW for t in results)

    async def test_search_no_filters_returns_all(self, db_session, sample_ticket):
        repo = TicketRepository(db_session)
        created = await repo.create(sample_ticket)

        results, total = await repo.search(TicketSearchFilters())
        ids = [t.id for t in results]
        assert created.id in ids

    async def test_compute_content_hash_is_stable(self):
        h1 = TicketRepository.compute_content_hash("  VPN Down  ", "Cannot connect.")
        h2 = TicketRepository.compute_content_hash("VPN Down", "Cannot connect.")
        assert h1 == h2

    async def test_compute_content_hash_differs_for_different_content(self):
        h1 = TicketRepository.compute_content_hash("VPN Down", "Cannot connect.")
        h2 = TicketRepository.compute_content_hash("DB Error", "Query timeout.")
        assert h1 != h2


# ── EmbeddingRepository ───────────────────────────────────────────────────────


class TestEmbeddingRepository:
    async def test_upsert_creates_embedding(self, db_session, sample_ticket):
        ticket_repo = TicketRepository(db_session)
        created = await ticket_repo.create(sample_ticket)

        emb_repo = EmbeddingRepository(db_session)
        vector = [0.1] * 384
        emb = await emb_repo.upsert(created.id, vector, "all-MiniLM-L6-v2")

        assert emb.ticket_id == created.id
        assert emb.model_version == "all-MiniLM-L6-v2"

    async def test_upsert_replaces_existing_embedding(self, db_session, sample_ticket):
        ticket_repo = TicketRepository(db_session)
        created = await ticket_repo.create(sample_ticket)
        emb_repo = EmbeddingRepository(db_session)

        await emb_repo.upsert(created.id, [0.1] * 384, "v1")
        emb = await emb_repo.upsert(created.id, [0.9] * 384, "v2")

        assert emb.model_version == "v2"

    async def test_find_similar_returns_self_as_top(self, db_session, sample_ticket):
        ticket_repo = TicketRepository(db_session)
        created = await ticket_repo.create(sample_ticket)
        emb_repo = EmbeddingRepository(db_session)

        vector = [0.5] * 384
        await emb_repo.upsert(created.id, vector, "v1")

        results = await emb_repo.find_similar(vector, top_k=1, similarity_threshold=0.0)
        assert len(results) >= 1
        assert results[0].ticket_id == created.id
        assert results[0].similarity_score > 0.99  # cosine similarity with itself ≈ 1.0

    async def test_find_similar_respects_threshold(self, db_session, sample_ticket):
        ticket_repo = TicketRepository(db_session)
        created = await ticket_repo.create(sample_ticket)
        emb_repo = EmbeddingRepository(db_session)

        vector = [0.5] * 384
        await emb_repo.upsert(created.id, vector, "v1")

        # Threshold of 1.01 should exclude everything
        results = await emb_repo.find_similar(vector, top_k=10, similarity_threshold=1.01)
        assert len(results) == 0


# ── KnowledgeBaseRepository ───────────────────────────────────────────────────


class TestKnowledgeBaseRepository:
    async def test_bulk_insert_returns_count(self, db_session):
        repo = KnowledgeBaseRepository(db_session)
        entries = [
            KnowledgeBaseEntry(
                title=f"Test KB entry {i}",
                description=f"Description {i}",
                category=TicketCategory.NETWORK,
                resolution=f"Resolution steps {i}",
                source="test",
            )
            for i in range(5)
        ]
        count = await repo.bulk_insert(entries)
        assert count == 5

    async def test_get_all_for_bm25_includes_inserted_entries(self, db_session):
        repo = KnowledgeBaseRepository(db_session)
        before = await repo.get_all_for_bm25()

        new_entry = KnowledgeBaseEntry(
            title="New entry",
            description="A new knowledge base entry",
            category=TicketCategory.DATABASE,
            resolution="Fix the database",
            source="test",
        )
        await repo.bulk_insert([new_entry])

        after = await repo.get_all_for_bm25()
        assert len(after) == len(before) + 1

    async def test_update_embedding_stores_vector(self, db_session, sample_kb_entry):
        repo = KnowledgeBaseRepository(db_session)
        created = await repo.create(sample_kb_entry)
        assert created.embedding is None

        vector = [0.3] * 384
        await repo.update_embedding(created.id, vector)

        updated = await repo.get_by_id(created.id)
        assert updated is not None
        assert updated.embedding is not None


# ── ResolutionRepository ──────────────────────────────────────────────────────


class TestResolutionRepository:
    async def test_get_by_ticket_id_returns_none_when_no_resolution(
        self, db_session, sample_ticket
    ):
        ticket_repo = TicketRepository(db_session)
        created = await ticket_repo.create(sample_ticket)

        res_repo = ResolutionRepository(db_session)
        result = await res_repo.get_by_ticket_id(created.id)
        assert result is None

    async def test_get_by_ticket_id_returns_resolution(self, db_session, sample_ticket):
        ticket_repo = TicketRepository(db_session)
        created = await ticket_repo.create(sample_ticket)

        res_repo = ResolutionRepository(db_session)
        resolution = Resolution(
            ticket_id=created.id,
            suggested_steps="Step 1: Restart the VPN client.",
            routing_decision=RoutingDecision.AUTO_RESOLVED,
            is_repeated_issue=False,
        )
        await res_repo.create(resolution)

        fetched = await res_repo.get_by_ticket_id(created.id)
        assert fetched is not None
        assert fetched.routing_decision == RoutingDecision.AUTO_RESOLVED

    async def test_add_feedback_persists(self, db_session, sample_ticket):
        ticket_repo = TicketRepository(db_session)
        created = await ticket_repo.create(sample_ticket)

        res_repo = ResolutionRepository(db_session)
        resolution = Resolution(
            ticket_id=created.id,
            routing_decision=RoutingDecision.ASSIGNED,
            is_repeated_issue=False,
        )
        saved_res = await res_repo.create(resolution)

        from src.db.models import FeedbackAction
        feedback = FeedbackLog(
            resolution_id=saved_res.id,
            agent_id="agent-001",
            action=FeedbackAction.ACCEPTED,
        )
        saved_fb = await res_repo.add_feedback(feedback)
        assert saved_fb.id is not None
        assert saved_fb.agent_id == "agent-001"
