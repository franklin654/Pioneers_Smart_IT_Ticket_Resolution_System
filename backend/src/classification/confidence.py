"""Confidence scoring: map class probabilities to HIGH/MEDIUM/LOW + multi-domain flag.

All thresholds come from Settings (never hardcoded), so they can be tuned
without code changes (docs/06_DATA_AND_EVALUATION.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.core.config import get_settings
from src.db.models import TicketCategory

ConfidenceLevel = Literal["high", "medium", "low"]


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    confidence: float
    confidence_level: ConfidenceLevel
    is_multi_domain: bool
    top_category: TicketCategory
    second_category: TicketCategory | None
    top2_gap: float


def score(
    class_probs: dict[TicketCategory, float],
    *,
    high_threshold: float | None = None,
    low_threshold: float | None = None,
    multi_domain_diff: float | None = None,
) -> ConfidenceResult:
    """Convert a probability distribution to a structured confidence result.

    Thresholds default to settings values; explicit overrides are accepted
    so unit tests can exercise boundary conditions without monkey-patching.
    """
    settings = get_settings()
    high_t = high_threshold if high_threshold is not None else settings.confidence_high_threshold
    low_t = low_threshold if low_threshold is not None else settings.confidence_low_threshold
    multi_t = (
        multi_domain_diff if multi_domain_diff is not None else settings.multi_domain_diff_threshold
    )

    sorted_cats = sorted(class_probs.items(), key=lambda kv: kv[1], reverse=True)
    top_cat, top_prob = sorted_cats[0]
    second_cat: TicketCategory | None = None
    top2_gap = 1.0

    if len(sorted_cats) >= 2:
        second_cat, second_prob = sorted_cats[1]
        top2_gap = top_prob - second_prob

    if top_prob >= high_t:
        level: ConfidenceLevel = "high"
    elif top_prob >= low_t:
        level = "medium"
    else:
        level = "low"

    is_multi_domain = top2_gap <= multi_t

    return ConfidenceResult(
        confidence=top_prob,
        confidence_level=level,
        is_multi_domain=is_multi_domain,
        top_category=top_cat,
        second_category=second_cat,
        top2_gap=top2_gap,
    )
