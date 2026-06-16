"""End-to-end pipeline latency and routing distribution evaluation.

Runs up to --sample WEBHOOK-source tickets through the full TicketOrchestrator
(classify → gate → retrieve → generate → evaluate → route) and reports:

  - Latency: p50 / p95 / p99 per-ticket wall-clock seconds
  - Routing distribution: auto_resolved, assigned, escalated, awaiting_review
  - awaiting_review_rate as a distinct bucket (new in v2)

Gate: p95 latency < 5 seconds.

Already-processed tickets (have an existing resolution) are not re-run; their
latency is estimated from (resolution.created_at − ticket.created_at). Tickets
that haven't been processed yet are run live and timed in this script.

Requires: trained classifier, embedded KB, Ollama or Claude API running.

Usage:
    python evaluation/end_to_end_eval.py
    python evaluation/end_to_end_eval.py --sample 30
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from collections import Counter

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.database import session_scope
from src.db.models import RoutingDecision, TicketSource
from src.db.repositories.classification_repo import ClassificationRepository
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)

_LATENCY_GATE_P95 = 5.0
_DEFAULT_SAMPLE = 50
_RANDOM_SEED = 42


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * pct / 100)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


async def _build_orchestrator_with_bm25(session: object) -> object:
    from src.agents.orchestrator import build_orchestrator
    from src.rag.knowledge_base import build_index

    from sqlalchemy.ext.asyncio import AsyncSession
    assert isinstance(session, AsyncSession)

    kb_repo = KnowledgeBaseRepository(session)
    ticket_repo = TicketRepository(session)
    classification_repo = ClassificationRepository(session)
    resolution_repo = ResolutionRepository(session)

    all_kb = await kb_repo.get_all_for_bm25()
    if not all_kb:
        raise RuntimeError(
            "No KB entries found. Run load_tickets.py + embed_knowledge_base.py first."
        )
    bm25_index = await build_index(all_kb)

    return build_orchestrator(
        ticket_repo=ticket_repo,
        classification_repo=classification_repo,
        resolution_repo=resolution_repo,
        kb_repo=kb_repo,
        bm25_index=bm25_index,
    )


async def _run(sample: int) -> float:
    settings = get_settings()
    _ = settings  # ensures config validation runs before any DB work

    async with session_scope() as session:
        repo = TicketRepository(session)
        all_tickets = await repo.get_by_source(TicketSource.WEBHOOK)

    if not all_tickets:
        raise RuntimeError(
            "No WEBHOOK-source tickets found. Run load_tickets.py first."
        )

    rng = random.Random(_RANDOM_SEED)
    sample_tickets = rng.sample(all_tickets, min(sample, len(all_tickets)))

    latencies: list[float] = []
    routing_counts: Counter[str] = Counter()
    live_runs = 0

    for ticket in sample_tickets:
        # If already processed: use timestamp delta as a latency estimate
        if ticket.resolution is not None:
            delta = (
                ticket.resolution.created_at - ticket.created_at
            ).total_seconds()
            latencies.append(max(0.0, delta))
            routing_counts[ticket.resolution.routing_decision.value] += 1
            continue

        # Live run — time the full orchestrator
        t_start = time.perf_counter()
        try:
            async with session_scope() as session:
                orch = await _build_orchestrator_with_bm25(session)
                t_repo = TicketRepository(session)
                t = await t_repo.get_with_relations(ticket.id)
                if t is None:
                    continue
                result = await orch.run(t)
                await session.commit()

            elapsed = time.perf_counter() - t_start
            latencies.append(elapsed)
            routing_counts[result.routing_decision.value] += 1
            live_runs += 1
        except Exception as exc:
            logger.warning("e2e_ticket_failed", ticket_id=str(ticket.id), error=str(exc))

    total = len(latencies)
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)

    total_routed = sum(routing_counts.values())
    awaiting_rate = routing_counts.get(RoutingDecision.AWAITING_REVIEW.value, 0) / max(total_routed, 1)

    print("\n" + "=" * 60)
    print("END-TO-END EVALUATION — Latency & Routing Distribution")
    print("=" * 60)
    print(f"WEBHOOK tickets total  : {len(all_tickets)}")
    print(f"Sample size            : {len(sample_tickets)}")
    print(f"Evaluated              : {total}")
    print(f"  From DB timestamps   : {total - live_runs}")
    print(f"  Live runs            : {live_runs}")
    print()
    print("Latency (seconds):")
    print(f"  p50 : {p50:.3f}s")
    print(f"  p95 : {p95:.3f}s  (gate < {_LATENCY_GATE_P95}s)")
    print(f"  p99 : {p99:.3f}s")
    print()
    print("Routing distribution:")
    for decision in (
        RoutingDecision.AUTO_RESOLVED,
        RoutingDecision.ASSIGNED,
        RoutingDecision.ESCALATED,
        RoutingDecision.AWAITING_REVIEW,
    ):
        count = routing_counts.get(decision.value, 0)
        pct = count / max(total_routed, 1) * 100
        print(f"  {decision.value:<20}: {count:4d}  ({pct:5.1f}%)")
    print(f"\nawaitng_review_rate    : {awaiting_rate * 100:.1f}%")
    print("=" * 60)

    logger.info(
        "e2e_eval_complete",
        total=total,
        p50=round(p50, 3),
        p95=round(p95, 3),
        p99=round(p99, 3),
        awaiting_review_rate=round(awaiting_rate, 4),
        routing_counts=dict(routing_counts),
    )
    return p95


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=_DEFAULT_SAMPLE,
        help="Maximum tickets to include in the sample (default: %(default)s)",
    )
    args = parser.parse_args()

    p95 = asyncio.run(_run(args.sample))

    if p95 >= _LATENCY_GATE_P95:
        print(f"\nFAIL — p95 latency {p95:.3f}s exceeds the gate of {_LATENCY_GATE_P95}s.")
        sys.exit(1)
    else:
        print(f"\nPASS — p95 latency {p95:.3f}s is within the gate of {_LATENCY_GATE_P95}s.")


if __name__ == "__main__":
    main()
