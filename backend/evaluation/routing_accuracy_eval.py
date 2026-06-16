"""Router determinism and accuracy check on the held-out set.

For every WEBHOOK ticket that has both a stored Classification and a stored
Resolution, re-run TicketRouter.decide() with the persisted inputs and compare
the result to the stored routing_decision.

Metric: agreement_rate (stored decision == re-computed decision).

This is tracked, not gated — a drift here means the router logic changed after
tickets were processed, or a threshold was tuned. It's a canary for unintended
router changes, not a hard quality bar.

Usage:
    python evaluation/routing_accuracy_eval.py
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy.orm import selectinload

from src.classification.classifier import ClassificationOutput
from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.database import session_scope
from src.db.models import Resolution, Ticket, TicketCategory, TicketSource
from src.routing.router import TicketRouter

logger = get_logger(__name__)


@dataclass
class RouterCheckResult:
    ticket_id: str
    stored_decision: str
    computed_decision: str
    agreed: bool


@dataclass
class RoutingAccuracyReport:
    results: list[RouterCheckResult] = field(default_factory=list)
    skipped: int = 0

    @property
    def agreement_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.agreed) / len(self.results)

    @property
    def disagreement_pairs(self) -> Counter[tuple[str, str]]:
        c: Counter[tuple[str, str]] = Counter()
        for r in self.results:
            if not r.agreed:
                c[(r.stored_decision, r.computed_decision)] += 1
        return c


def _reconstruct_classification(
    ticket: Ticket,
) -> ClassificationOutput | None:
    """Reconstruct a ClassificationOutput from stored Classification row."""
    cls = ticket.classification
    if cls is None:
        return None

    all_probs: dict[str, float] = {
        item["category"]: item["probability"]
        for item in (cls.top_categories or [])
        if "category" in item and "probability" in item
    }

    return ClassificationOutput(
        category=TicketCategory(cls.predicted_category.value),
        confidence=cls.confidence,
        confidence_level=cls.confidence_level.value,  # "high" / "medium" / "low"
        is_multi_domain=cls.is_multi_domain,
        top2_gap=0.0,  # not persisted; not used in routing logic
        classification_method=cls.classification_method.value,
        all_probabilities=all_probs,
    )


async def _load_webhook_tickets(
    session: object,
) -> list[Ticket]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)

    stmt = (
        select(Ticket)
        .where(Ticket.source == TicketSource.WEBHOOK)
        .options(
            selectinload(Ticket.classification),
            selectinload(Ticket.resolution).selectinload(Resolution.feedback_logs),
        )
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def _run() -> float:
    settings = get_settings()
    router = TicketRouter(quality_threshold=settings.llm_quality_threshold)

    async with session_scope() as session:
        tickets = await _load_webhook_tickets(session)

    report = RoutingAccuracyReport()

    for ticket in tickets:
        if ticket.classification is None or ticket.resolution is None:
            report.skipped += 1
            continue

        quality_score = ticket.resolution.llm_quality_score
        if quality_score is None:
            # awaiting_review tickets have no quality score — skip
            report.skipped += 1
            continue

        classification = _reconstruct_classification(ticket)
        if classification is None:
            report.skipped += 1
            continue

        computed = router.decide(classification, quality_score)
        stored_decision = ticket.resolution.routing_decision.value
        computed_decision = computed.decision.value

        report.results.append(
            RouterCheckResult(
                ticket_id=str(ticket.id),
                stored_decision=stored_decision,
                computed_decision=computed_decision,
                agreed=stored_decision == computed_decision,
            )
        )

    print("\n" + "=" * 60)
    print("ROUTING ACCURACY — Determinism Check on WEBHOOK Set")
    print("=" * 60)
    print(f"WEBHOOK tickets       : {len(tickets)}")
    print(f"Evaluated             : {len(report.results)}")
    print(f"Skipped               : {report.skipped}")
    print(f"\nAgreement rate        : {report.agreement_rate * 100:.1f}%  [tracked, not gated]")

    if report.disagreement_pairs:
        print("\nDisagreements (stored → computed):")
        for (stored, computed), count in report.disagreement_pairs.most_common():
            print(f"  {stored:<20} → {computed:<20} : {count}")
    else:
        print("\nNo disagreements — router is fully deterministic on this set.")

    print("=" * 60)

    logger.info(
        "routing_accuracy_complete",
        evaluated=len(report.results),
        skipped=report.skipped,
        agreement_rate=round(report.agreement_rate, 4),
    )
    return report.agreement_rate


def main() -> None:
    configure_logging()
    rate = asyncio.run(_run())
    print(f"\nINFO — Agreement rate {rate * 100:.1f}% (tracked, not gated).")


if __name__ == "__main__":
    main()
