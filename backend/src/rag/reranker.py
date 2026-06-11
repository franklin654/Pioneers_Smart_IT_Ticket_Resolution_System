"""MMR (Maximal Marginal Relevance) reranker for the RAG pipeline.

MMR balances relevance (how well a candidate matches the query) with diversity
(how different the candidate is from already-selected entries).  The formula is:

    MMR(c) = λ · relevance(c) − (1−λ) · max_{s ∈ S} cosine_sim(c, s)

Where S is the set of already-selected entries.  Because all KB embeddings are
L2-normalized, cosine similarity reduces to a dot product — no extra normalisation
is needed at query time.

The reranker is the last step before the LLM generator and operates on the
fused candidate list produced by :class:`~src.rag.retriever.HybridRetriever`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from src.core.exceptions import RAGRetrievalError
from src.core.logging import get_logger
from src.rag.retriever import RetrievedEntry

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)


class MMRReranker:
    """Reranks retrieved KB entries using Maximal Marginal Relevance.

    Selects entries that are both highly relevant to the query *and* diverse
    relative to each other.  λ controls the trade-off: λ=1.0 is pure
    relevance ranking; λ=0.0 is pure diversity selection.

    Args:
        settings: Application settings; reads ``mmr_lambda`` and ``rag_top_k``.
    """

    def __init__(self, settings: "Settings") -> None:
        self._lambda = settings.mmr_lambda
        self._default_top_k = settings.rag_top_k

    def rerank(
        self,
        candidates: list[RetrievedEntry],
        top_k: int | None = None,
    ) -> list[RetrievedEntry]:
        """Apply MMR to select a diverse-yet-relevant subset of candidates.

        The greedy algorithm selects one entry per iteration:
        1. First pick: highest ``combined_score`` (no diversity penalty yet).
        2. Subsequent picks: highest MMR score = λ·relevance − (1−λ)·max_sim.

        Args:
            candidates: Entries from :class:`~src.rag.retriever.HybridRetriever`,
                sorted by ``combined_score`` descending.  Each entry should carry
                a populated ``.embedding`` for diversity scoring.
            top_k: Number of entries to return.  Defaults to
                ``settings.rag_top_k``.

        Returns:
            Reranked list of :class:`~src.rag.retriever.RetrievedEntry` (up to
            ``top_k``), ordered by MMR selection sequence.

        Raises:
            RAGRetrievalError: If ``candidates`` is non-empty but every entry
                has ``embedding=None`` (cannot compute diversity).
        """
        if not candidates:
            return []

        k = top_k if top_k is not None else self._default_top_k

        # Partition entries into those that have embeddings and those that don't.
        # Entries without embeddings can still be selected but contribute 0
        # cosine similarity when acting as already-selected entries.
        with_emb = [r for r in candidates if r.embedding is not None]
        without_emb = [r for r in candidates if r.embedding is None]

        if not with_emb and candidates:
            raise RAGRetrievalError(
                message="MMR reranking failed: no candidate has an embedding vector",
                detail={"candidate_count": len(candidates)},
            )

        # Ordered candidate pool: entries with embeddings first (preferred for
        # scoring), then entries without embeddings as fallback.
        ordered: list[RetrievedEntry] = list(with_emb) + list(without_emb)

        selected: list[RetrievedEntry] = []
        remaining: list[RetrievedEntry] = list(ordered)

        while remaining and len(selected) < k:
            if not selected:
                # First selection: pick by highest combined_score.
                best = max(remaining, key=lambda r: r.combined_score)
            else:
                # Compute MMR score for each remaining candidate.
                best = self._pick_best(remaining, selected)

            selected.append(best)
            remaining.remove(best)

        logger.debug(
            "MMR reranking complete",
            extra={
                "metadata": {
                    "input_candidates": len(candidates),
                    "selected": len(selected),
                    "top_k": k,
                    "lambda": self._lambda,
                }
            },
        )
        return selected

    # ── Private helpers ────────────────────────────────────────────────────

    def _pick_best(
        self,
        remaining: list[RetrievedEntry],
        selected: list[RetrievedEntry],
    ) -> RetrievedEntry:
        """Return the remaining entry with the highest MMR score."""
        best_entry = remaining[0]
        best_score = float("-inf")

        for candidate in remaining:
            relevance = candidate.combined_score
            max_sim = self._max_similarity_to_selected(candidate, selected)
            mmr_score = self._lambda * relevance - (1 - self._lambda) * max_sim

            if mmr_score > best_score:
                best_score = mmr_score
                best_entry = candidate

        return best_entry

    def _max_similarity_to_selected(
        self,
        candidate: RetrievedEntry,
        selected: list[RetrievedEntry],
    ) -> float:
        """Return the maximum cosine similarity from ``candidate`` to any selected entry.

        If the candidate has no embedding, similarity is treated as 0 (cannot
        compute — behaves as if it is maximally diverse).
        """
        if candidate.embedding is None:
            return 0.0

        max_sim = 0.0
        for sel in selected:
            sim = self._cosine_sim(candidate.embedding, sel.embedding)
            if sim > max_sim:
                max_sim = sim
        return max_sim

    @staticmethod
    def _cosine_sim(
        a: list[float],
        b: list[float] | None,
    ) -> float:
        """Dot product of two L2-normalised vectors (equals cosine similarity).

        Args:
            a: First vector (must not be None).
            b: Second vector; returns 0.0 if None.

        Returns:
            Scalar cosine similarity in [0, 1] for normalised vectors.
        """
        if b is None:
            return 0.0
        return float(np.dot(a, b))
