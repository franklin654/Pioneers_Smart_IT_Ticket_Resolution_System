"""Confidence scoring and multi-domain detection for classification outputs.

Converts the raw probability distribution from the Logistic Regression
classifier into a structured ``ClassificationOutput`` that drives routing
decisions downstream.

All thresholds are read from application settings so they can be tuned
without code changes:
    - ``confidence_high_threshold`` (default 0.85)
    - ``confidence_low_threshold``  (default 0.60)
    - ``multi_domain_diff_threshold`` (default 0.15)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.db.models import TicketCategory

if TYPE_CHECKING:
    from src.core.config import Settings


class ConfidenceLevel(str, enum.Enum):
    """Discretized confidence band derived from the top-1 class probability.

    Used by the routing engine to decide between auto-resolve, assign, and
    escalate paths without hard-coding numeric thresholds in business logic.
    """

    HIGH = "high"      # probability >= confidence_high_threshold (default 0.85)
    MEDIUM = "medium"  # confidence_low_threshold <= probability < high (default 0.60)
    LOW = "low"        # probability < confidence_low_threshold (default 0.60)


@dataclass(frozen=True)
class ClassificationOutput:
    """Immutable classification result ready for persistence and routing.

    Attributes:
        predicted_category: The category with the highest probability.
        confidence: Top-1 class probability (0–1).
        confidence_level: Discretized band: HIGH, MEDIUM, or LOW.
        top_categories: Up to 3 ``{"category": str, "probability": float}``
            dicts sorted by probability descending.  Used to display
            alternative interpretations in the UI.
        is_multi_domain: ``True`` when the gap between the top-2 probabilities
            is below ``multi_domain_diff_threshold``, signalling the ticket
            spans multiple IT domains and should be escalated.
        classification_method: Identifier of the model that produced this
            output (e.g. ``"logistic_regression_v1"``).
    """

    predicted_category: TicketCategory
    confidence: float
    confidence_level: ConfidenceLevel
    top_categories: list[dict]
    is_multi_domain: bool
    classification_method: str


class ConfidenceScorer:
    """Converts raw classifier probabilities into a :class:`ClassificationOutput`.

    Args:
        settings: Application settings providing threshold values.
    """

    def __init__(self, settings: "Settings") -> None:
        self._high_threshold = settings.confidence_high_threshold
        self._low_threshold = settings.confidence_low_threshold
        self._multi_domain_threshold = settings.multi_domain_diff_threshold

    def score(
        self,
        category_probabilities: dict[TicketCategory, float],
        classification_method: str,
    ) -> ClassificationOutput:
        """Build a :class:`ClassificationOutput` from a probability distribution.

        Args:
            category_probabilities: Mapping of every :class:`TicketCategory` to
                its predicted probability.  Values should sum to approximately
                1.0 (standard classifier output).
            classification_method: Identifier string for the model version,
                e.g. ``"logistic_regression_v1"``.  Stored for audit trails.

        Returns:
            Fully populated :class:`ClassificationOutput`.
        """
        # Sort by probability descending — stable sort preserves order for ties
        sorted_probs: list[tuple[TicketCategory, float]] = sorted(
            category_probabilities.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        predicted_category, confidence = sorted_probs[0]
        confidence_level = self._get_confidence_level(confidence)
        top_categories = [
            {"category": cat.value, "probability": round(prob, 6)}
            for cat, prob in sorted_probs[:3]
        ]
        is_multi_domain = self._is_multi_domain(sorted_probs)

        return ClassificationOutput(
            predicted_category=predicted_category,
            confidence=round(confidence, 6),
            confidence_level=confidence_level,
            top_categories=top_categories,
            is_multi_domain=is_multi_domain,
            classification_method=classification_method,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _get_confidence_level(self, confidence: float) -> ConfidenceLevel:
        """Map a float probability to a :class:`ConfidenceLevel` band.

        Boundaries are inclusive on the high side:
            - HIGH:   confidence >= high_threshold
            - MEDIUM: low_threshold <= confidence < high_threshold
            - LOW:    confidence < low_threshold

        Args:
            confidence: Top-1 class probability from the classifier.

        Returns:
            Corresponding :class:`ConfidenceLevel` enum member.
        """
        if confidence >= self._high_threshold:
            return ConfidenceLevel.HIGH
        if confidence >= self._low_threshold:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW

    def _is_multi_domain(
        self,
        sorted_probs: list[tuple[TicketCategory, float]],
    ) -> bool:
        """Return ``True`` when the top-2 probability gap is below the threshold.

        A small gap between the best and second-best category indicates the
        classifier is uncertain which domain the ticket belongs to, which is
        the signal to escalate to a human specialist.

        Args:
            sorted_probs: Probability pairs sorted descending by probability.
                Must contain at least one entry.

        Returns:
            ``True`` if the ticket is multi-domain, ``False`` otherwise.
        """
        if len(sorted_probs) < 2:
            return False

        top_prob = sorted_probs[0][1]
        second_prob = sorted_probs[1][1]
        return (top_prob - second_prob) < self._multi_domain_threshold
