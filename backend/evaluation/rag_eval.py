"""RAG retrieval quality evaluation script.

Evaluates the hybrid retriever using a **leave-one-out** approach:
for each knowledge base entry, treat its text as a query and check
whether the retriever returns that same entry in the top-k results.

Metrics:
    - **Precision@k**: fraction of queries where the source entry appears
      in the top-k results (binary per query: 1 if found, 0 if not).
    - **Recall@k**: identical to Precision@k for leave-one-out evaluation
      (there is exactly one relevant entry per query).
    - **MRR** (Mean Reciprocal Rank): average of 1/rank for the first
      relevant result (0 if not found within top-k).

Usage::

    python -m evaluation.rag_eval
    python -m evaluation.rag_eval --top-k 5 --fail-under-precision 0.80

Exit codes:
    0 — all metrics passed
    1 — one or more metrics below threshold
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.database import get_async_session
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.embedding.generator import EmbeddingGenerator
from src.rag.knowledge_base import KnowledgeBase
from src.rag.retriever import HybridRetriever

logger = get_logger(__name__)


# ── Config and result dataclasses ─────────────────────────────────────────────


@dataclass
class RAGEvalConfig:
    """Thresholds and parameters for the RAG evaluation run.

    Attributes:
        top_k: Number of results to retrieve per query.
        fail_under_precision: Minimum required Precision@k.
        fail_under_recall: Minimum required Recall@k.
        fail_under_mrr: Minimum required MRR.
    """

    top_k: int = 5
    fail_under_precision: float = 0.80
    fail_under_recall: float = 0.85
    fail_under_mrr: float = 0.70


@dataclass
class RAGEvalResult:
    """Results of a RAG evaluation run.

    Attributes:
        precision_at_k: Fraction of queries where source entry was in top-k.
        recall_at_k: Same as precision for leave-one-out evaluation.
        mrr: Mean Reciprocal Rank across all queries.
        num_queries: Total number of KB entries evaluated.
        k: The top-k value used.
        passed: True if all metrics meet the configured thresholds.
    """

    precision_at_k: float
    recall_at_k: float
    mrr: float
    num_queries: int
    k: int
    passed: bool


# ── Core evaluation logic ─────────────────────────────────────────────────────


async def evaluate(
    session: AsyncSession,
    config: RAGEvalConfig,
) -> RAGEvalResult:
    """Run the leave-one-out RAG evaluation against the knowledge base.

    Args:
        session: Active async database session.
        config: Evaluation configuration and thresholds.

    Returns:
        :class:`RAGEvalResult` with computed metrics.
    """
    settings = get_settings()
    kb_repo = KnowledgeBaseRepository(session)
    embedding_gen = EmbeddingGenerator(settings)

    kb = KnowledgeBase(repo=kb_repo, embedding_generator=embedding_gen, settings=settings)
    await kb.build_bm25_index(force_rebuild=True)

    retriever = HybridRetriever(kb=kb, kb_repo=kb_repo, settings=settings)
    entries = await kb_repo.get_all_for_bm25()

    if not entries:
        logger.warning("No KB entries found — evaluation skipped")
        return RAGEvalResult(
            precision_at_k=0.0,
            recall_at_k=0.0,
            mrr=0.0,
            num_queries=0,
            k=config.top_k,
            passed=False,
        )

    print(f"Evaluating RAG retrieval on {len(entries):,} KB entries...")

    hits = 0
    reciprocal_ranks: list[float] = []

    for entry in entries:
        query_text = f"{entry.title} {entry.resolution}"
        query_vector = embedding_gen.encode_single(query_text)

        try:
            results = await retriever.retrieve(
                query_text=query_text,
                query_vector=query_vector,
                top_k=config.top_k,
            )
        except Exception:
            # If retrieval fails for this query, count it as a miss.
            reciprocal_ranks.append(0.0)
            continue

        result_ids = [str(r.entry.id) for r in results]
        entry_id = str(entry.id)

        if entry_id in result_ids:
            hits += 1
            rank = result_ids.index(entry_id) + 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)

    n = len(entries)
    precision = hits / n
    recall = precision  # identical for leave-one-out (1 relevant per query)
    mrr = sum(reciprocal_ranks) / n if n > 0 else 0.0

    passed = (
        precision >= config.fail_under_precision
        and recall >= config.fail_under_recall
        and mrr >= config.fail_under_mrr
    )

    return RAGEvalResult(
        precision_at_k=precision,
        recall_at_k=recall,
        mrr=mrr,
        num_queries=n,
        k=config.top_k,
        passed=passed,
    )


def print_report(result: RAGEvalResult, config: RAGEvalConfig) -> None:
    """Print a human-readable evaluation report to stdout.

    Args:
        result: Computed evaluation metrics.
        config: Thresholds used for pass/fail determination.
    """
    print(f"\nPrecision@{result.k}: {result.precision_at_k:.3f}  (min {config.fail_under_precision:.2f})")
    print(f"Recall@{result.k}:    {result.recall_at_k:.3f}  (min {config.fail_under_recall:.2f})")
    print(f"MRR:           {result.mrr:.3f}  (min {config.fail_under_mrr:.2f})")
    print(f"Queries:       {result.num_queries:,}")

    if result.passed:
        print("\nPASS: All metrics meet minimum thresholds")
    else:
        print("\nFAIL: One or more metrics below threshold")
        if result.precision_at_k < config.fail_under_precision:
            print(f"  ✗ Precision@{result.k} {result.precision_at_k:.3f} < {config.fail_under_precision:.2f}")
        if result.recall_at_k < config.fail_under_recall:
            print(f"  ✗ Recall@{result.k} {result.recall_at_k:.3f} < {config.fail_under_recall:.2f}")
        if result.mrr < config.fail_under_mrr:
            print(f"  ✗ MRR {result.mrr:.3f} < {config.fail_under_mrr:.2f}")


# ── CLI entry point ────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Evaluate RAG retrieval quality (Precision@k, Recall@k, MRR)"
    )
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to retrieve")
    parser.add_argument(
        "--fail-under-precision",
        type=float,
        default=0.80,
        metavar="THRESHOLD",
        help="Minimum Precision@k (default: 0.80)",
    )
    parser.add_argument(
        "--fail-under-recall",
        type=float,
        default=0.85,
        metavar="THRESHOLD",
        help="Minimum Recall@k (default: 0.85)",
    )
    parser.add_argument(
        "--fail-under-mrr",
        type=float,
        default=0.70,
        metavar="THRESHOLD",
        help="Minimum MRR (default: 0.70)",
    )
    return parser.parse_args()


async def main() -> int:
    """Run evaluation and return exit code (0=pass, 1=fail)."""
    args = parse_args()
    config = RAGEvalConfig(
        top_k=args.top_k,
        fail_under_precision=args.fail_under_precision,
        fail_under_recall=args.fail_under_recall,
        fail_under_mrr=args.fail_under_mrr,
    )

    async for session in get_async_session():
        result = await evaluate(session, config)
        print_report(result, config)
        return 0 if result.passed else 1

    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
