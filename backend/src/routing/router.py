"""Deterministic ticket routing decision engine.

Takes the classifier output and LLM quality score and applies five ordered
rules to produce one of three outcomes: AUTO_RESOLVED, ASSIGNED, ESCALATED.

No I/O is performed here — this is pure computation so the logic is trivially
unit-testable and never blocks the event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.logging import get_logger
from src.db.models import ConfidenceLevel, RoutingDecision, TicketCategory

if TYPE_CHECKING:
    from src.classification.confidence import ClassificationOutput

logger = get_logger(__name__)

# ── Department registry ────────────────────────────────────────────────────────

_DEPARTMENT_MAP: dict[TicketCategory, str] = {
    TicketCategory.INFRASTRUCTURE: "infrastructure-team",
    TicketCategory.APPLICATION: "application-team",
    TicketCategory.SECURITY: "security-team",
    TicketCategory.DATABASE: "database-team",
    TicketCategory.ACCESS_MANAGEMENT: "iam-team",
    TicketCategory.NETWORK: "network-team",
}

_LLM_QUALITY_THRESHOLD: float = 3.5


# ── Result dataclass ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RoutingResult:
    """Immutable routing outcome produced by :class:`TicketRouter`.

    Attributes:
        decision: One of AUTO_RESOLVED, ASSIGNED, or ESCALATED.
        assigned_department: Department string (set for AUTO_RESOLVED and
            ASSIGNED); ``None`` for ESCALATED.
        escalation_reason: Human-readable explanation (set for ESCALATED);
            ``None`` for AUTO_RESOLVED and ASSIGNED.
    """

    decision: RoutingDecision
    assigned_department: str | None
    escalation_reason: str | None


# ── Router ─────────────────────────────────────────────────────────────────────


class TicketRouter:
    """Applies five ordered routing rules to produce a :class:`RoutingResult`.

    Rules (first match wins):
        1. ``is_multi_domain=True`` → ESCALATED (needs specialist)
        2. ``confidence_level=LOW`` → ESCALATED (classifier uncertain)
        3. ``llm_quality_score < 3.5`` → ESCALATED (resolution not actionable)
        4. ``confidence_level=HIGH`` → AUTO_RESOLVED
        5. ``confidence_level=MEDIUM`` → ASSIGNED (agent gets AI suggestion)
    """

    def decide(
        self,
        classification: "ClassificationOutput",
        llm_quality_score: float,
    ) -> RoutingResult:
        """Evaluate routing rules and return the first matching outcome.

        Args:
            classification: Output from :class:`~src.classification.classifier.TicketClassifier`.
            llm_quality_score: Mean score (0–5.0) from the LLM evaluator.
                A score of 0.0 indicates a parse failure and always triggers
                escalation.

        Returns:
            :class:`RoutingResult` with decision, department, and reason.
        """
        category = classification.predicted_category
        level = classification.confidence_level
        confidence = classification.confidence

        # Rule 1: Multi-domain — always escalate regardless of confidence or score
        if classification.is_multi_domain:
            result = RoutingResult(
                decision=RoutingDecision.ESCALATED,
                assigned_department=None,
                escalation_reason="Multi-domain ticket requires specialist review",
            )
            self._log(result, confidence, llm_quality_score)
            return result

        # Rule 2: Low classifier confidence
        if level == ConfidenceLevel.LOW:
            result = RoutingResult(
                decision=RoutingDecision.ESCALATED,
                assigned_department=None,
                escalation_reason=f"Low classifier confidence ({confidence:.2f})",
            )
            self._log(result, confidence, llm_quality_score)
            return result

        # Rule 3: LLM resolution quality too low
        if llm_quality_score < _LLM_QUALITY_THRESHOLD:
            result = RoutingResult(
                decision=RoutingDecision.ESCALATED,
                assigned_department=None,
                escalation_reason=(
                    f"Resolution quality below threshold "
                    f"({llm_quality_score:.1f}/5.0)"
                ),
            )
            self._log(result, confidence, llm_quality_score)
            return result

        department = _DEPARTMENT_MAP[category]

        # Rule 4: High confidence + good quality → auto-resolve
        if level == ConfidenceLevel.HIGH:
            result = RoutingResult(
                decision=RoutingDecision.AUTO_RESOLVED,
                assigned_department=department,
                escalation_reason=None,
            )
            self._log(result, confidence, llm_quality_score)
            return result

        # Rule 5: Medium confidence + good quality → assign to department
        result = RoutingResult(
            decision=RoutingDecision.ASSIGNED,
            assigned_department=department,
            escalation_reason=None,
        )
        self._log(result, confidence, llm_quality_score)
        return result

    @staticmethod
    def _log(result: RoutingResult, confidence: float, quality: float) -> None:
        logger.info(
            "Routing decision made",
            extra={
                "metadata": {
                    "decision": result.decision.value,
                    "department": result.assigned_department,
                    "escalation_reason": result.escalation_reason,
                    "confidence": confidence,
                    "llm_quality_score": quality,
                }
            },
        )
