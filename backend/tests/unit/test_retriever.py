"""Unit tests for HybridRetriever (src/rag/retriever.py).

All tests mock KnowledgeBaseRepository and KnowledgeBase — no DB or
model download required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import RAGRetrievalError
from src.db.models import TicketCategory
from src.db.repositories.knowledge_base_repo import SimilarKBResult
from src.rag.retriever import HybridRetriever, RetrievedEntry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings(
    candidate_pool: int = 10,
    dense_weight: float = 0.7,
    bm25_weight: float = 0.3,
) -> MagicMock:
    s = MagicMock()
    s.rag_candidate_pool = candidate_pool
    s.rag_dense_weight = dense_weight
    s.rag_bm25_weight = bm25_weight
    return s


def _make_kb_entry(entry_id: str | None = None, category: TicketCategory = TicketCategory.NETWORK) -> MagicMock:
    entry = MagicMock()
    entry.id = uuid.UUID(entry_id) if entry_id else uuid.uuid4()
    entry.category = category
    entry.embedding = [0.1] * 384
    entry.title = "Sample KB entry"
    entry.resolution = "Restart the service"
    return entry


def _make_dense_result(entry_id: uuid.UUID, score: float) -> SimilarKBResult:
    return SimilarKBResult(
        entry_id=entry_id,
        title="Sample",
        resolution="Restart",
        category=TicketCategory.NETWORK,
        similarity_score=score,
    )


def _make_retriever(
    kb_repo: MagicMock | None = None,
    kb: MagicMock | None = None,
    settings: MagicMock | None = None,
) -> HybridRetriever:
    return HybridRetriever(
        kb=kb or MagicMock(),
        kb_repo=kb_repo or AsyncMock(),
        settings=settings or _make_settings(),
    )


# ── Happy path ────────────────────────────────────────────────────────────────


class TestHybridRetrieverHappyPath:
    async def test_dense_and_bm25_results_are_merged(self):
        entry = _make_kb_entry()
        dense_result = _make_dense_result(entry.id, score=0.8)

        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = [dense_result]
        kb_repo.get_by_id.return_value = entry

        bm25_entry = _make_kb_entry(str(uuid.uuid4()))
        bm25_index = MagicMock()
        import numpy as np
        bm25_index.get_scores.return_value = np.array([0.6, 0.0])

        kb = MagicMock()
        kb.get_bm25_index.return_value = bm25_index
        kb.get_bm25_entries.return_value = [bm25_entry, _make_kb_entry()]

        retriever = _make_retriever(kb_repo=kb_repo, kb=kb)
        results = await retriever.retrieve(
            query_text="network issue",
            query_vector=[0.1] * 384,
        )

        assert len(results) > 0
        assert all(isinstance(r, RetrievedEntry) for r in results)

    async def test_results_sorted_by_combined_score_descending(self):
        entry_a = _make_kb_entry()
        entry_b = _make_kb_entry()
        dense_a = _make_dense_result(entry_a.id, score=0.9)
        dense_b = _make_dense_result(entry_b.id, score=0.5)

        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = [dense_a, dense_b]
        kb_repo.get_by_id.side_effect = lambda eid: entry_a if eid == entry_a.id else entry_b

        kb = MagicMock()
        kb.get_bm25_index.return_value = None
        kb.get_bm25_entries.return_value = []

        retriever = _make_retriever(kb_repo=kb_repo, kb=kb)
        results = await retriever.retrieve(
            query_text="test",
            query_vector=[0.1] * 384,
        )

        assert results[0].combined_score >= results[-1].combined_score

    async def test_only_dense_results_still_returns_entries(self):
        entry = _make_kb_entry()
        dense_result = _make_dense_result(entry.id, score=0.75)

        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = [dense_result]
        kb_repo.get_by_id.return_value = entry

        kb = MagicMock()
        kb.get_bm25_index.return_value = None  # no BM25 index
        kb.get_bm25_entries.return_value = []

        retriever = _make_retriever(kb_repo=kb_repo, kb=kb)
        results = await retriever.retrieve(
            query_text="test",
            query_vector=[0.1] * 384,
        )

        assert len(results) == 1
        assert results[0].dense_score == pytest.approx(0.75, abs=1e-4)

    async def test_only_bm25_results_still_returns_entries(self):
        entry = _make_kb_entry()

        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = []  # dense returns nothing

        import numpy as np
        bm25_index = MagicMock()
        bm25_index.get_scores.return_value = np.array([0.8])

        kb = MagicMock()
        kb.get_bm25_index.return_value = bm25_index
        kb.get_bm25_entries.return_value = [entry]

        retriever = _make_retriever(kb_repo=kb_repo, kb=kb)
        results = await retriever.retrieve(
            query_text="server down",
            query_vector=[0.1] * 384,
        )

        assert len(results) == 1
        assert results[0].bm25_score == pytest.approx(1.0, abs=1e-4)

    async def test_results_capped_at_top_k(self):
        entries = [_make_kb_entry() for _ in range(15)]
        dense_results = [_make_dense_result(e.id, score=0.8) for e in entries]

        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = dense_results
        entry_map = {e.id: e for e in entries}
        kb_repo.get_by_id.side_effect = lambda eid: entry_map.get(eid)

        kb = MagicMock()
        kb.get_bm25_index.return_value = None
        kb.get_bm25_entries.return_value = []

        settings = _make_settings(candidate_pool=10)
        retriever = _make_retriever(kb_repo=kb_repo, kb=kb, settings=settings)
        results = await retriever.retrieve(
            query_text="test",
            query_vector=[0.1] * 384,
        )

        assert len(results) <= 10

    async def test_same_entry_in_both_not_duplicated(self):
        entry = _make_kb_entry()
        dense_result = _make_dense_result(entry.id, score=0.8)

        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = [dense_result]
        kb_repo.get_by_id.return_value = entry

        import numpy as np
        bm25_index = MagicMock()
        bm25_index.get_scores.return_value = np.array([0.6])

        kb = MagicMock()
        kb.get_bm25_index.return_value = bm25_index
        kb.get_bm25_entries.return_value = [entry]

        retriever = _make_retriever(kb_repo=kb_repo, kb=kb)
        results = await retriever.retrieve(
            query_text="vpn down",
            query_vector=[0.1] * 384,
        )

        entry_ids = [str(r.entry.id) for r in results]
        assert len(entry_ids) == len(set(entry_ids)), "Duplicate entry IDs found"

    async def test_category_filter_passed_to_dense_search(self):
        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = []

        kb = MagicMock()
        kb.get_bm25_index.return_value = None
        kb.get_bm25_entries.return_value = []

        settings = _make_settings(candidate_pool=5)
        retriever = _make_retriever(kb_repo=kb_repo, kb=kb, settings=settings)

        try:
            await retriever.retrieve(
                query_text="firewall issue",
                query_vector=[0.1] * 384,
                category_filter=TicketCategory.SECURITY,
            )
        except RAGRetrievalError:
            pass  # expected when both return nothing

        kb_repo.search_similar.assert_called_once()
        call_kwargs = kb_repo.search_similar.call_args.kwargs
        assert call_kwargs.get("category_filter") == TicketCategory.SECURITY


# ── Fusion score calculation ──────────────────────────────────────────────────


class TestFusionScores:
    async def test_combined_score_computed_correctly(self):
        # entry_a is in both dense and BM25; entry_b is BM25-only (higher raw score).
        # BM25 normalises by max score: scores=[0.6, 1.0] → max=1.0 → norm=[0.6, 1.0].
        # entry_a bm25_score = 0.6, dense_score = 0.8 → combined = 0.7*0.8 + 0.3*0.6 = 0.74
        import numpy as np

        entry_a = _make_kb_entry()
        entry_b = _make_kb_entry()  # BM25-only entry to anchor the normalisation max
        dense_result = _make_dense_result(entry_a.id, score=0.8)

        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = [dense_result]
        kb_repo.get_by_id.return_value = entry_a

        bm25_index = MagicMock()
        # scores[0] = entry_a (0.6), scores[1] = entry_b (1.0) → max = 1.0, no rescaling
        bm25_index.get_scores.return_value = np.array([0.6, 1.0])

        kb = MagicMock()
        kb.get_bm25_index.return_value = bm25_index
        kb.get_bm25_entries.return_value = [entry_a, entry_b]

        settings = _make_settings(dense_weight=0.7, bm25_weight=0.3)
        retriever = _make_retriever(kb_repo=kb_repo, kb=kb, settings=settings)
        results = await retriever.retrieve(
            query_text="test query",
            query_vector=[0.1] * 384,
        )

        # Find entry_a's result (it was in both dense and BM25)
        result_a = next(r for r in results if r.entry.id == entry_a.id)
        assert result_a.combined_score == pytest.approx(0.74, abs=1e-4)


# ── Negative cases ────────────────────────────────────────────────────────────


class TestHybridRetrieverNegative:
    async def test_both_empty_raises_rag_retrieval_error(self):
        kb_repo = AsyncMock()
        kb_repo.search_similar.return_value = []

        kb = MagicMock()
        kb.get_bm25_index.return_value = None
        kb.get_bm25_entries.return_value = []

        retriever = _make_retriever(kb_repo=kb_repo, kb=kb)
        with pytest.raises(RAGRetrievalError):
            await retriever.retrieve(
                query_text="test",
                query_vector=[0.1] * 384,
            )

    async def test_dense_exception_falls_back_to_bm25(self):
        entry = _make_kb_entry()

        kb_repo = AsyncMock()
        kb_repo.search_similar.side_effect = RuntimeError("pgvector timeout")

        import numpy as np
        bm25_index = MagicMock()
        bm25_index.get_scores.return_value = np.array([0.9])

        kb = MagicMock()
        kb.get_bm25_index.return_value = bm25_index
        kb.get_bm25_entries.return_value = [entry]

        retriever = _make_retriever(kb_repo=kb_repo, kb=kb)
        # Should not raise — dense failure is logged and BM25 takes over
        results = await retriever.retrieve(
            query_text="network outage",
            query_vector=[0.1] * 384,
        )
        assert len(results) > 0
