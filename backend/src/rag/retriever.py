"""Hybrid retriever combining dense (pgvector) and sparse (BM25) search.

The two retrieval strategies complement each other:
    - **Dense** (70 % weight): pgvector cosine similarity captures semantic
      meaning — finds tickets that say the same thing differently.
    - **BM25** (30 % weight): keyword overlap catches exact technical terms,
      error codes, and product names the embedding model may under-weight.

Fusion uses a simple weighted score combination (not Reciprocal Rank Fusion)
so that scores remain interpretable and adjustable via environment variables.
The fused list is then passed to the MMR reranker to balance relevance with
diversity before being handed to the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from src.core.exceptions import RAGRetrievalError
from src.core.logging import get_logger
from src.db.models import KnowledgeBaseEntry, TicketCategory
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository

if TYPE_CHECKING:
    from src.core.config import Settings
    from src.rag.knowledge_base import KnowledgeBase

logger = get_logger(__name__)


@dataclass
class RetrievedEntry:
    """A single knowledge base entry returned by the retriever.

    Attributes:
        entry: The full :class:`KnowledgeBaseEntry` ORM object.
        dense_score: Cosine similarity from pgvector (0–1), or 0 if not
            retrieved by dense search.
        bm25_score: Normalised BM25 score (0–1), or 0 if not retrieved by
            keyword search.
        combined_score: Weighted fusion of dense and BM25 scores.
        embedding: The entry's 384-dim vector (populated for MMR reranking).
    """

    entry: KnowledgeBaseEntry
    dense_score: float = 0.0
    bm25_score: float = 0.0
    combined_score: float = 0.0
    embedding: list[float] | None = None


class HybridRetriever:
    """Retrieves knowledge base entries using dense + BM25 hybrid search.

    Args:
        kb: :class:`KnowledgeBase` holding the BM25 index and entries.
        kb_repo: :class:`KnowledgeBaseRepository` for dense vector search.
        settings: Application settings providing weight and pool size values.
    """

    def __init__(
        self,
        kb: "KnowledgeBase",
        kb_repo: KnowledgeBaseRepository,
        settings: "Settings",
    ) -> None:
        self._kb = kb
        self._kb_repo = kb_repo
        self._settings = settings

    async def retrieve(
        self,
        query_text: str,
        query_vector: list[float],
        top_k: int | None = None,
        category_filter: TicketCategory | None = None,
    ) -> list[RetrievedEntry]:
        """Run hybrid retrieval and return a ranked candidate list.

        Fetches ``rag_candidate_pool`` results from each strategy, merges by
        entry ID, computes the weighted combined score, and returns the top
        ``top_k`` candidates sorted by ``combined_score`` descending.

        Args:
            query_text: Raw ticket text used for BM25 keyword matching.
            query_vector: 384-dim embedding of the query ticket.
            top_k: Number of results to return; defaults to
                ``settings.rag_candidate_pool`` (pre-MMR).
            category_filter: If provided, restricts dense search to entries
                in this category.

        Returns:
            List of :class:`RetrievedEntry` sorted by ``combined_score`` desc.

        Raises:
            RAGRetrievalError: If both retrieval strategies fail.
        """
        pool_size = top_k or self._settings.rag_candidate_pool
        dense_weight = self._settings.rag_dense_weight
        bm25_weight = self._settings.rag_bm25_weight

        dense_results = await self._retrieve_dense(query_vector, pool_size, category_filter)
        bm25_results = self._retrieve_bm25(query_text, pool_size)

        if not dense_results and not bm25_results:
            raise RAGRetrievalError(
                message="Both dense and BM25 retrieval returned no results",
                detail={"query_length": len(query_text)},
            )

        merged = self._fuse(dense_results, bm25_results, dense_weight, bm25_weight)
        merged.sort(key=lambda r: r.combined_score, reverse=True)
        return merged[:pool_size]

    # ── Private helpers ────────────────────────────────────────────────────

    async def _retrieve_dense(
        self,
        query_vector: list[float],
        top_k: int,
        category_filter: TicketCategory | None,
    ) -> list[RetrievedEntry]:
        """Query pgvector for the top-k most similar KB entries."""
        try:
            results = await self._kb_repo.search_similar(
                query_vector=query_vector,
                top_k=top_k,
                category_filter=category_filter,
            )
            dense: list[RetrievedEntry] = []
            for r in results:
                entry = await self._kb_repo.get_by_id(r.entry_id)
                if entry:
                    dense.append(
                        RetrievedEntry(
                            entry=entry,
                            dense_score=r.similarity_score,
                            embedding=entry.embedding,
                        )
                    )
            return dense
        except Exception as exc:
            logger.warning(
                "Dense retrieval failed",
                extra={"metadata": {"error": str(exc)}},
            )
            return []

    def _retrieve_bm25(
        self,
        query_text: str,
        top_k: int,
    ) -> list[RetrievedEntry]:
        """Query the in-memory BM25 index for keyword-matched entries."""
        bm25_index = self._kb.get_bm25_index()
        entries = self._kb.get_bm25_entries()

        if bm25_index is None or not entries:
            return []

        try:
            tokens = query_text.lower().split()
            scores = bm25_index.get_scores(tokens)

            # Normalise scores to [0, 1]
            max_score = float(scores.max()) if scores.max() > 0 else 1.0
            norm_scores = scores / max_score

            top_indices = np.argsort(norm_scores)[::-1][:top_k]
            return [
                RetrievedEntry(
                    entry=entries[i],
                    bm25_score=float(norm_scores[i]),
                    embedding=entries[i].embedding,
                )
                for i in top_indices
                if norm_scores[i] > 0
            ]
        except Exception as exc:
            logger.warning(
                "BM25 retrieval failed",
                extra={"metadata": {"error": str(exc)}},
            )
            return []

    @staticmethod
    def _fuse(
        dense: list[RetrievedEntry],
        bm25: list[RetrievedEntry],
        dense_weight: float,
        bm25_weight: float,
    ) -> list[RetrievedEntry]:
        """Merge dense and BM25 results by entry ID and compute combined scores.

        Entries appearing in only one list receive 0 for the missing score.
        """
        merged: dict[str, RetrievedEntry] = {}

        for r in dense:
            key = str(r.entry.id)
            merged[key] = r

        for r in bm25:
            key = str(r.entry.id)
            if key in merged:
                merged[key].bm25_score = r.bm25_score
            else:
                merged[key] = r

        for r in merged.values():
            r.combined_score = (
                dense_weight * r.dense_score + bm25_weight * r.bm25_score
            )

        return list(merged.values())
