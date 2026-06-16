"""Phase 4 gate: Precision@5 ≥ 0.80 on a stratified held-out split of KB entries.

Method: 10% of each KB category is withheld as query probes; retrieval
searches the remaining 90% without category filter. A retrieved entry is
relevant if its category matches the probe's category. This evaluates the
retrieval component independently of classifier quality on consistently-labeled
training data.

Usage:
    python evaluation/rag_eval.py
"""

from __future__ import annotations

import asyncio
import random
import sys

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.database import session_scope
from src.db.models import KnowledgeBaseEntry, TicketCategory
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.embedding.generator import EmbeddingGenerator
from src.rag.knowledge_base import KnowledgeBaseIndex, build_index
from src.rag.reranker import MMRReranker
from src.rag.retriever import HybridRetriever

logger = get_logger(__name__)

_PRECISION_GATE = 0.80
_TOP_K = 5
_HOLDOUT_FRACTION = 0.10
_RANDOM_SEED = 42


def _stratified_split(
    entries: list[KnowledgeBaseEntry], fraction: float, seed: int
) -> tuple[list[KnowledgeBaseEntry], list[KnowledgeBaseEntry]]:
    """Return (probes, index_pool) — probes are the held-out fraction."""
    rng = random.Random(seed)
    by_cat: dict[TicketCategory, list[KnowledgeBaseEntry]] = {}
    for e in entries:
        if e.category is None:
            continue
        by_cat.setdefault(e.category, []).append(e)

    probes: list[KnowledgeBaseEntry] = []
    pool: list[KnowledgeBaseEntry] = []
    for cat_entries in by_cat.values():
        shuffled = list(cat_entries)
        rng.shuffle(shuffled)
        n_probe = max(1, int(len(shuffled) * fraction))
        probes.extend(shuffled[:n_probe])
        pool.extend(shuffled[n_probe:])
    return probes, pool


async def _run() -> float:
    settings = get_settings()
    generator = EmbeddingGenerator(
        model_name=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
    )

    async with session_scope() as session:
        kb_repo = KnowledgeBaseRepository(session)
        all_kb = await kb_repo.get_all_for_bm25()

    if not all_kb:
        raise RuntimeError("No KB entries found. Run load_tickets.py then embed_knowledge_base.py.")

    probes, pool = _stratified_split(all_kb, _HOLDOUT_FRACTION, _RANDOM_SEED)

    bm25_index: KnowledgeBaseIndex = await build_index(pool)
    reranker = MMRReranker(generator)

    async with session_scope() as session:
        kb_repo_live = KnowledgeBaseRepository(session)
        retriever = HybridRetriever(kb_repo_live, generator, bm25_index)

        total, relevant_sum = 0, 0
        for probe in probes:
            if probe.category is None:
                continue
            query = f"{probe.title} {probe.description}"
            candidates = await retriever.retrieve(query, category_filter=None)
            # Exclude the probe itself from results
            candidates = [c for c in candidates if c.id != probe.id]
            reranked = await reranker.rerank(query, candidates, top_k=_TOP_K)

            hits = sum(1 for e in reranked if e.category == probe.category)
            relevant_sum += hits / _TOP_K if reranked else 0
            total += 1

    precision_at_k = relevant_sum / total if total else 0.0

    print("\n" + "=" * 60)
    print("PHASE 4 GATE — RAG Retrieval Evaluation")
    print("=" * 60)
    print(f"KB entries total  : {len(all_kb)}")
    print(f"Index pool size   : {len(pool)}")
    print(f"Probe queries     : {total}")
    print(f"Precision@{_TOP_K}       : {precision_at_k:.4f}  (gate ≥ {_PRECISION_GATE})")
    print("=" * 60)

    logger.info(
        "rag_eval_complete",
        precision_at_k=round(precision_at_k, 4),
        probes=total,
        pool=len(pool),
    )
    return precision_at_k


def main() -> None:
    configure_logging()
    p = asyncio.run(_run())

    if p < _PRECISION_GATE:
        print(f"\nFAIL — Precision@{_TOP_K} {p:.4f} is below the gate of {_PRECISION_GATE}.")
        sys.exit(1)
    else:
        print(f"\nPASS — Precision@{_TOP_K} {p:.4f} meets the gate of {_PRECISION_GATE}.")


if __name__ == "__main__":
    main()
