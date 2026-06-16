"""Full-pipeline evaluation on the WEBHOOK-source held-out set.

Runs every WEBHOOK ticket through the complete TicketOrchestrator (or skips if
already processed), then reports:

  1. Classification accuracy — predicted category vs. ticket.category label
  2. Routing distribution — auto_resolved / assigned / escalated / awaiting_review
  3. LLM quality score distribution — mean, min, max (where available)
  4. awaiting_review_rate — fraction of tickets parked at the pre-generation gate
  5. Failure count — tickets that raised an exception

All metrics are TRACKED, not gated — this evaluator catches train/eval skew and
gives visibility into pipeline behaviour on the harder, labelled held-out set.

Requires: trained classifier, embedded KB, Ollama or Claude API running.

Usage:
    python evaluation/holdout_eval.py
    python evaluation/holdout_eval.py --rerun   # force re-run even if already processed
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.database import session_scope
from src.db.models import RoutingDecision, TicketSource
from src.db.repositories.classification_repo import ClassificationRepository
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)


@dataclass
class HoldoutReport:
    total: int = 0
    already_processed: int = 0
    newly_processed: int = 0
    failed: int = 0
    classification_correct: int = 0
    classification_total: int = 0
    routing_counts: Counter[str] = field(default_factory=Counter)
    quality_scores: list[float] = field(default_factory=list)

    @property
    def classification_accuracy(self) -> float:
        if self.classification_total == 0:
            return 0.0
        return self.classification_correct / self.classification_total

    @property
    def awaiting_review_rate(self) -> float:
        total_routed = sum(self.routing_counts.values())
        if total_routed == 0:
            return 0.0
        return self.routing_counts.get(RoutingDecision.AWAITING_REVIEW.value, 0) / total_routed

    @property
    def quality_mean(self) -> float:
        return sum(self.quality_scores) / len(self.quality_scores) if self.quality_scores else 0.0


async def _build_orchestrator(session: object) -> object:
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


async def _run(rerun: bool) -> HoldoutReport:
    settings = get_settings()
    _ = settings

    async with session_scope() as session:
        repo = TicketRepository(session)
        all_tickets = await repo.get_by_source(TicketSource.WEBHOOK)

    if not all_tickets:
        raise RuntimeError(
            "No WEBHOOK-source tickets found. Run load_tickets.py first."
        )

    report = HoldoutReport(total=len(all_tickets))

    # Process each ticket, building one orchestrator per ticket (own DB session)
    for ticket in all_tickets:
        ticket_label = ticket.category  # labeled ground truth

        async with session_scope() as session:
            t_repo = TicketRepository(session)
            t = await t_repo.get_with_relations(ticket.id)
            if t is None:
                report.failed += 1
                continue

            # Skip already-processed tickets unless --rerun
            if t.resolution is not None and not rerun:
                report.already_processed += 1
                # Still collect metrics from stored data
                if t.classification is not None and ticket_label is not None:
                    report.classification_total += 1
                    if t.classification.predicted_category == ticket_label:
                        report.classification_correct += 1
                report.routing_counts[t.resolution.routing_decision.value] += 1
                if t.resolution.llm_quality_score is not None:
                    report.quality_scores.append(t.resolution.llm_quality_score)
                continue

            try:
                orch = await _build_orchestrator(session)
                result = await orch.run(t)
                await session.commit()
                report.newly_processed += 1

                # Collect routing metric
                report.routing_counts[result.routing_decision.value] += 1

                # Collect quality score
                if result.llm_quality_score is not None:
                    report.quality_scores.append(result.llm_quality_score)

                # Collect classification accuracy (compare orchestrator output to label)
                if ticket_label is not None and result.routing_decision != RoutingDecision.AWAITING_REVIEW:
                    # Re-read classification written by orchestrator
                    await session.refresh(t)
                    if t.classification is not None:
                        report.classification_total += 1
                        if t.classification.predicted_category == ticket_label:
                            report.classification_correct += 1

            except Exception as exc:
                logger.error(
                    "holdout_ticket_failed",
                    ticket_id=str(ticket.id),
                    error=str(exc),
                )
                report.failed += 1

    print("\n" + "=" * 60)
    print("HOLDOUT EVALUATION — Full Pipeline on WEBHOOK Set")
    print("=" * 60)
    print(f"Total WEBHOOK tickets      : {report.total}")
    print(f"  Already processed        : {report.already_processed}")
    print(f"  Newly processed this run : {report.newly_processed}")
    print(f"  Failed                   : {report.failed}")
    print()
    print("Classification accuracy (model vs. label):")
    print(f"  Correct / Total          : {report.classification_correct} / {report.classification_total}")
    print(f"  Accuracy                 : {report.classification_accuracy * 100:.1f}%  [tracked]")
    print()
    print("Routing distribution:")
    total_routed = sum(report.routing_counts.values())
    for decision in (
        RoutingDecision.AUTO_RESOLVED,
        RoutingDecision.ASSIGNED,
        RoutingDecision.ESCALATED,
        RoutingDecision.AWAITING_REVIEW,
    ):
        count = report.routing_counts.get(decision.value, 0)
        pct = count / max(total_routed, 1) * 100
        print(f"  {decision.value:<20}: {count:4d}  ({pct:5.1f}%)")
    print(f"\nawaiting_review_rate       : {report.awaiting_review_rate * 100:.1f}%  [tracked]")
    print()
    if report.quality_scores:
        print("LLM quality score (for resolved tickets):")
        print(f"  Mean : {report.quality_mean:.3f}")
        print(f"  Min  : {min(report.quality_scores):.3f}")
        print(f"  Max  : {max(report.quality_scores):.3f}")
    print("=" * 60)

    logger.info(
        "holdout_eval_complete",
        total=report.total,
        newly_processed=report.newly_processed,
        failed=report.failed,
        classification_accuracy=round(report.classification_accuracy, 4),
        awaiting_review_rate=round(report.awaiting_review_rate, 4),
        quality_mean=round(report.quality_mean, 3) if report.quality_scores else None,
    )
    return report


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Force re-processing even if tickets already have resolutions.",
    )
    args = parser.parse_args()

    try:
        report = asyncio.run(_run(args.rerun))
    except RuntimeError as exc:
        print(f"\nERROR — {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        f"\nINFO — Holdout evaluation complete. "
        f"Classification accuracy: {report.classification_accuracy * 100:.1f}%, "
        f"awaiting_review_rate: {report.awaiting_review_rate * 100:.1f}%  (tracked, not gated)"
    )


if __name__ == "__main__":
    main()
