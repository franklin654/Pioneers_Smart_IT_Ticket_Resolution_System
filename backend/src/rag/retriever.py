"""Hybrid retriever: 70% dense (pgvector cosine) + 30% BM25 score fusion.

Weights come from Settings (`rag_dense_weight`, `rag_bm25_weight`). The
candidate pool is `rag_candidate_pool` per leg; final top-k is `rag_top_k`.
"""

from __future__ import annotations

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models import KnowledgeBaseEntry, TicketCategory
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.embedding.generator import EmbeddingGenerator
from src.rag.knowledge_base import KnowledgeBaseIndex

logger = get_logger(__name__)


class HybridRetriever:
    def __init__(
        self,
        kb_repo: KnowledgeBaseRepository,
        generator: EmbeddingGenerator,
        bm25_index: KnowledgeBaseIndex,
    ) -> None:
        self._kb_repo = kb_repo
        self._generator = generator
        self._bm25_index = bm25_index
        settings = get_settings()
        self._dense_weight = settings.rag_dense_weight
        self._bm25_weight = settings.rag_bm25_weight
        self._top_k = settings.rag_top_k
        self._candidate_pool = settings.rag_candidate_pool

    async def retrieve(
        self,
        query: str,
        category_filter: TicketCategory | None = None,
    ) -> list[KnowledgeBaseEntry]:
        """Return `top_k` KB entries fused from dense + BM25 legs."""
        query_vector = await self._generator.encode_one(query)

        dense_results: list[tuple[KnowledgeBaseEntry, float]] = (
            await self._kb_repo.search_similar(
                query_vector,
                top_k=self._candidate_pool,
                category_filter=category_filter,
            )
        )

        bm25_results: list[tuple[KnowledgeBaseEntry, float]] = self._bm25_index.search(
            query, top_k=self._candidate_pool, category_filter=category_filter
        )

        scores: dict[str, float] = {}
        id_to_entry: dict[str, KnowledgeBaseEntry] = {}

        # Dense: lower distance = higher similarity; convert to [0,1] similarity
        if dense_results:
            max_sim = 1.0
            for entry, dist in dense_results:
                key = str(entry.id)
                sim = max(0.0, 1.0 - dist)
                scores[key] = scores.get(key, 0.0) + self._dense_weight * (sim / max_sim)
                id_to_entry[key] = entry

        # BM25: normalise by max score in this batch
        if bm25_results:
            max_bm25 = max(s for _, s in bm25_results) or 1.0
            for entry, bm25_score in bm25_results:
                if bm25_score <= 0:
                    continue
                key = str(entry.id)
                scores[key] = scores.get(key, 0.0) + self._bm25_weight * (bm25_score / max_bm25)
                id_to_entry[key] = entry

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        results = [id_to_entry[k] for k, _ in ranked[: self._top_k]]

        logger.debug(
            "retrieval_complete",
            query_len=len(query),
            dense_candidates=len(dense_results),
            bm25_candidates=len(bm25_results),
            returned=len(results),
        )
        return results
