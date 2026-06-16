"""TicketRouter — pure Python, no LLM, exactly auditable rules.

Two entry points share one rule set (docs/03_BACKEND_DESIGN.md §142):
- `pre_generation_check`: Rules 1-2 only (before RAG/generation runs)
- `decide`: all 5 rules (after generation + quality scoring)
"""

from __future__ import annotations

from dataclasses import dataclass

from src.classification.classifier import ClassificationOutput
from src.core.config import get_settings
from src.db.models import RoutingDecision


@dataclass(frozen=True, slots=True)
class RoutingResult:
    decision: RoutingDecision
    reason: str


class TicketRouter:
    def __init__(self, quality_threshold: float | None = None) -> None:
        settings = get_settings()
        self._quality_threshold = (
            quality_threshold if quality_threshold is not None else settings.llm_quality_threshold
        )

    def pre_generation_check(
        self, classification: ClassificationOutput
    ) -> RoutingResult | None:
        """Rules 1-2: fire before RAG/generation. Returns None if neither matches."""
        # Rule 1 — multi-domain ambiguity
        if classification.is_multi_domain:
            return RoutingResult(
                decision=RoutingDecision.AWAITING_REVIEW,
                reason=(
                    f"Multi-domain ticket (top-2 gap={classification.top2_gap:.3f}); "
                    "human reclassification required before generation."
                ),
            )
        # Rule 2 — low confidence
        if classification.confidence_level == "low":
            return RoutingResult(
                decision=RoutingDecision.AWAITING_REVIEW,
                reason=(
                    f"Confidence too low ({classification.confidence:.3f}) to generate "
                    "reliably; human reclassification required."
                ),
            )
        return None

    def decide(
        self,
        classification: ClassificationOutput,
        llm_quality_score: float,
    ) -> RoutingResult:
        """All 5 rules. `pre_generation_check` is called internally so there
        is exactly one source of truth for Rules 1 & 2."""
        pre = self.pre_generation_check(classification)
        if pre is not None:
            return pre

        # Rule 3 — poor generation quality
        if llm_quality_score < self._quality_threshold:
            return RoutingResult(
                decision=RoutingDecision.ESCALATED,
                reason=(
                    f"LLM quality score {llm_quality_score:.2f} is below threshold "
                    f"{self._quality_threshold:.2f}; escalating for human review."
                ),
            )

        # Rule 4 — high confidence + good quality → auto-resolve
        if classification.confidence_level == "high":
            return RoutingResult(
                decision=RoutingDecision.AUTO_RESOLVED,
                reason=(
                    f"High confidence ({classification.confidence:.3f}) and quality "
                    f"score {llm_quality_score:.2f} ≥ {self._quality_threshold:.2f}."
                ),
            )

        # Rule 5 — medium confidence + good quality → assign
        return RoutingResult(
            decision=RoutingDecision.ASSIGNED,
            reason=(
                f"Medium confidence ({classification.confidence:.3f}); "
                f"quality score {llm_quality_score:.2f} ≥ {self._quality_threshold:.2f}. "
                "Routed to support team for review."
            ),
        )
