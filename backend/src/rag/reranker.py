"""MMR (Maximal Marginal Relevance) reranker.

Balances relevance to the query against diversity among selected items.
λ=0.7 from Settings (`mmr_lambda`) — higher λ favours relevance.

Embedding computation is CPU-bound; all encode calls use asyncio.to_thread
via EmbeddingGenerator (audit fix H1).
"""

from __future__ import annotations

import asyncio

import numpy as np

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models import KnowledgeBaseEntry
from src.embedding.generator import EmbeddingGenerator

logger = get_logger(__name__)


def _mmr_sync(
    query_vec: np.ndarray,
    doc_vecs: np.ndarray,
    lambda_: float,
    top_k: int,
) -> list[int]:
    """Return indices of `top_k` documents selected by MMR."""
    selected: list[int] = []
    remaining = list(range(len(doc_vecs)))

    for _ in range(min(top_k, len(doc_vecs))):
        best_idx = -1
        best_score = float("-inf")

        for i in remaining:
            rel = float(query_vec @ doc_vecs[i])
            if selected:
                redundancy = float(np.max(doc_vecs[selected] @ doc_vecs[i]))
            else:
                redundancy = 0.0
            score = lambda_ * rel - (1 - lambda_) * redundancy
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx == -1:
            break
        selected.append(best_idx)
        remaining.remove(best_idx)

    return selected


class MMRReranker:
    def __init__(self, generator: EmbeddingGenerator) -> None:
        self._generator = generator
        settings = get_settings()
        self._lambda = settings.mmr_lambda
        self._top_k = settings.rag_top_k

    async def rerank(
        self,
        query: str,
        candidates: list[KnowledgeBaseEntry],
        top_k: int | None = None,
    ) -> list[KnowledgeBaseEntry]:
        if not candidates:
            return []

        k = top_k if top_k is not None else self._top_k
        if len(candidates) <= k:
            return candidates

        doc_texts = [f"{e.title} {e.description}" for e in candidates]
        all_texts = [query] + doc_texts
        all_vecs_raw: list[list[float]] = await self._generator.encode(all_texts)

        query_vec = np.array(all_vecs_raw[0], dtype=np.float32)
        doc_vecs = np.array(all_vecs_raw[1:], dtype=np.float32)

        indices = await asyncio.to_thread(_mmr_sync, query_vec, doc_vecs, self._lambda, k)

        result = [candidates[i] for i in indices]
        logger.debug("mmr_rerank_complete", candidates=len(candidates), selected=len(result))
        return result
