"""Unit tests for MMRReranker (src/rag/reranker.py).

Tests use small 4-dim L2-normalised embeddings for clarity.
No DB, no model download required.
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.core.exceptions import RAGRetrievalError
from src.db.models import KnowledgeBaseEntry, TicketCategory
from src.rag.reranker import MMRReranker
from src.rag.retriever import RetrievedEntry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings(mmr_lambda: float = 0.7, rag_top_k: int = 5) -> MagicMock:
    s = MagicMock()
    s.mmr_lambda = mmr_lambda
    s.rag_top_k = rag_top_k
    return s


def _l2_norm(v: list[float]) -> list[float]:
    """Return L2-normalised version of a vector."""
    arr = np.array(v, dtype=float)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return v
    return (arr / norm).tolist()


def _make_entry(
    combined_score: float = 0.5,
    embedding: list[float] | None = None,
) -> RetrievedEntry:
    """Build a RetrievedEntry with a mock ORM object and given scores."""
    kb = MagicMock(spec=KnowledgeBaseEntry)
    kb.id = uuid.uuid4()
    kb.title = "Test KB entry"
    kb.resolution = "Restart the service"
    kb.category = TicketCategory.NETWORK
    return RetrievedEntry(
        entry=kb,
        dense_score=combined_score,
        bm25_score=0.0,
        combined_score=combined_score,
        embedding=embedding,
    )


# Basis vectors (orthogonal, then normalised) for diversity tests
_V1 = _l2_norm([1.0, 0.0, 0.0, 0.0])
_V2 = _l2_norm([0.0, 1.0, 0.0, 0.0])
_V3 = _l2_norm([0.0, 0.0, 1.0, 0.0])
_V4 = _l2_norm([0.0, 0.0, 0.0, 1.0])


# ── Happy path ────────────────────────────────────────────────────────────────


class TestMMRRerankerHappyPath:
    def test_empty_candidates_returns_empty(self):
        reranker = MMRReranker(_make_settings())
        assert reranker.rerank([]) == []

    def test_single_candidate_returned(self):
        reranker = MMRReranker(_make_settings())
        entry = _make_entry(combined_score=0.9, embedding=_V1)
        result = reranker.rerank([entry], top_k=5)
        assert result == [entry]

    def test_returns_at_most_top_k(self):
        reranker = MMRReranker(_make_settings(rag_top_k=3))
        candidates = [_make_entry(0.9 - i * 0.1, embedding=_V1) for i in range(5)]
        result = reranker.rerank(candidates, top_k=3)
        assert len(result) == 3

    def test_top_k_larger_than_candidates_returns_all(self):
        reranker = MMRReranker(_make_settings())
        candidates = [_make_entry(0.8, embedding=_V1), _make_entry(0.6, embedding=_V2)]
        result = reranker.rerank(candidates, top_k=10)
        assert len(result) == 2

    def test_first_selected_has_highest_combined_score(self):
        reranker = MMRReranker(_make_settings(mmr_lambda=0.7))
        high = _make_entry(combined_score=0.9, embedding=_V1)
        low = _make_entry(combined_score=0.3, embedding=_V2)
        mid = _make_entry(combined_score=0.6, embedding=_V3)
        result = reranker.rerank([mid, low, high], top_k=3)
        assert result[0].combined_score == pytest.approx(0.9, abs=1e-6)

    def test_pure_relevance_order_matches_combined_score(self):
        """With λ=1.0 diversity has zero weight → order == combined_score desc."""
        reranker = MMRReranker(_make_settings(mmr_lambda=1.0))
        c1 = _make_entry(0.9, embedding=_V1)
        c2 = _make_entry(0.7, embedding=_V2)
        c3 = _make_entry(0.5, embedding=_V3)
        result = reranker.rerank([c3, c1, c2], top_k=3)
        scores = [r.combined_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_pure_diversity_second_item_is_orthogonal(self):
        """With λ=0.0 relevance has zero weight → second pick is most diverse."""
        reranker = MMRReranker(_make_settings(mmr_lambda=0.0))
        # All have same combined_score; first pick is arbitrary.
        c1 = _make_entry(0.5, embedding=_V1)
        c2 = _make_entry(0.5, embedding=_V2)   # orthogonal to V1 → max sim = 0
        c3 = _make_entry(0.5, embedding=_V1)   # identical to first pick → max sim = 1
        result = reranker.rerank([c1, c2, c3], top_k=3)
        # After picking c1 (V1), c2 (V2) has sim=0 to c1 and c3 (V1) has sim=1 to c1.
        # λ=0 → MMR(c2) = 0 - 1*0 = 0, MMR(c3) = 0 - 1*1 = -1 → c2 wins.
        assert result[1] is c2

    def test_default_top_k_from_settings_used(self):
        reranker = MMRReranker(_make_settings(rag_top_k=2))
        candidates = [_make_entry(0.9 - i * 0.1, embedding=_V1) for i in range(5)]
        result = reranker.rerank(candidates)  # no explicit top_k
        assert len(result) == 2


# ── Edge cases with missing embeddings ───────────────────────────────────────


class TestMMRRerankerEmbeddingEdgeCases:
    def test_all_embeddings_none_raises_rag_retrieval_error(self):
        reranker = MMRReranker(_make_settings())
        candidates = [_make_entry(0.8, embedding=None) for _ in range(3)]
        with pytest.raises(RAGRetrievalError):
            reranker.rerank(candidates)

    def test_some_embeddings_none_skipped_as_candidates(self):
        reranker = MMRReranker(_make_settings())
        with_emb = _make_entry(0.8, embedding=_V1)
        without_emb = _make_entry(0.9, embedding=None)  # higher score but no embedding
        result = reranker.rerank([without_emb, with_emb], top_k=2)
        # with_emb must appear in result; without_emb may appear as fallback
        entry_ids = [r.entry.id for r in result]
        assert with_emb.entry.id in entry_ids


# ── Cosine similarity helper ──────────────────────────────────────────────────


class TestCosineSimHelper:
    def test_identical_vectors_return_one(self):
        reranker = MMRReranker(_make_settings())
        v = _l2_norm([1.0, 2.0, 3.0, 4.0])
        assert reranker._cosine_sim(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors_return_zero(self):
        reranker = MMRReranker(_make_settings())
        assert reranker._cosine_sim(_V1, _V2) == pytest.approx(0.0, abs=1e-6)

    def test_none_second_arg_returns_zero(self):
        reranker = MMRReranker(_make_settings())
        assert reranker._cosine_sim(_V1, None) == pytest.approx(0.0, abs=1e-6)
