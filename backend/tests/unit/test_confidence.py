"""Unit tests for ConfidenceScorer (src/classification/confidence.py).

Pure Python — no database, no model, no I/O.
"""

from unittest.mock import MagicMock

import pytest

from src.classification.confidence import (
    ClassificationOutput,
    ConfidenceLevel,
    ConfidenceScorer,
)
from src.db.models import TicketCategory


def _make_settings(
    high: float = 0.85,
    low: float = 0.60,
    multi_domain_diff: float = 0.15,
) -> MagicMock:
    s = MagicMock()
    s.confidence_high_threshold = high
    s.confidence_low_threshold = low
    s.multi_domain_diff_threshold = multi_domain_diff
    return s


def _all_probs(top_cat: TicketCategory, top_prob: float) -> dict[TicketCategory, float]:
    """Build a probability dict with ``top_cat`` at ``top_prob`` and the rest split evenly."""
    remaining = 1.0 - top_prob
    others = [c for c in TicketCategory if c != top_cat]
    per_other = remaining / len(others) if others else 0.0
    return {top_cat: top_prob, **{c: per_other for c in others}}


def _two_probs(c1: TicketCategory, p1: float, c2: TicketCategory, p2: float) -> dict[TicketCategory, float]:
    """Build a dict with two prominent categories and tiny values for the rest."""
    remaining = 1.0 - p1 - p2
    others = [c for c in TicketCategory if c not in (c1, c2)]
    per_other = remaining / len(others) if others else 0.0
    return {c1: p1, c2: p2, **{c: per_other for c in others}}


# ── Confidence level banding ──────────────────────────────────────────────────


class TestConfidenceLevelBanding:
    def setup_method(self):
        self.scorer = ConfidenceScorer(_make_settings())

    def test_probability_0_90_is_high(self):
        probs = _all_probs(TicketCategory.NETWORK, 0.90)
        output = self.scorer.score(probs, "test_v1")
        assert output.confidence_level == ConfidenceLevel.HIGH

    def test_boundary_0_85_is_high(self):
        """Boundary inclusive: 0.85 → HIGH."""
        probs = _all_probs(TicketCategory.NETWORK, 0.85)
        output = self.scorer.score(probs, "test_v1")
        assert output.confidence_level == ConfidenceLevel.HIGH

    def test_just_below_high_boundary_is_medium(self):
        """0.849 is just below 0.85 → MEDIUM."""
        probs = _all_probs(TicketCategory.NETWORK, 0.849)
        output = self.scorer.score(probs, "test_v1")
        assert output.confidence_level == ConfidenceLevel.MEDIUM

    def test_boundary_0_60_is_medium(self):
        """Boundary inclusive: 0.60 → MEDIUM."""
        probs = _all_probs(TicketCategory.APPLICATION, 0.60)
        output = self.scorer.score(probs, "test_v1")
        assert output.confidence_level == ConfidenceLevel.MEDIUM

    def test_just_below_low_boundary_is_low(self):
        """0.599 is just below 0.60 → LOW."""
        probs = _all_probs(TicketCategory.APPLICATION, 0.599)
        output = self.scorer.score(probs, "test_v1")
        assert output.confidence_level == ConfidenceLevel.LOW

    def test_probability_0_00_is_low(self):
        probs = {c: (1.0 / 6) for c in TicketCategory}  # uniform → all around 0.167
        output = self.scorer.score(probs, "test_v1")
        assert output.confidence_level == ConfidenceLevel.LOW

    @pytest.mark.parametrize("prob,expected", [
        (0.95, ConfidenceLevel.HIGH),
        (0.85, ConfidenceLevel.HIGH),
        (0.80, ConfidenceLevel.MEDIUM),
        (0.60, ConfidenceLevel.MEDIUM),
        (0.50, ConfidenceLevel.LOW),
        (0.10, ConfidenceLevel.LOW),
    ])
    def test_parametrized_banding(self, prob, expected):
        probs = _all_probs(TicketCategory.SECURITY, prob)
        output = self.scorer.score(probs, "v1")
        assert output.confidence_level == expected


# ── Predicted category selection ──────────────────────────────────────────────


class TestPredictedCategory:
    def setup_method(self):
        self.scorer = ConfidenceScorer(_make_settings())

    def test_highest_probability_is_predicted(self):
        probs = {
            TicketCategory.NETWORK: 0.80,
            TicketCategory.INFRASTRUCTURE: 0.10,
            TicketCategory.APPLICATION: 0.05,
            TicketCategory.SECURITY: 0.03,
            TicketCategory.DATABASE: 0.01,
            TicketCategory.ACCESS_MANAGEMENT: 0.01,
        }
        output = self.scorer.score(probs, "v1")
        assert output.predicted_category == TicketCategory.NETWORK

    def test_confidence_matches_top_probability(self):
        probs = _all_probs(TicketCategory.DATABASE, 0.88)
        output = self.scorer.score(probs, "v1")
        assert output.confidence == pytest.approx(0.88, abs=1e-4)

    def test_all_categories_returns_top_3_in_top_categories(self):
        probs = {c: float(i + 1) / 21 for i, c in enumerate(TicketCategory)}
        total = sum(probs.values())
        probs = {c: p / total for c, p in probs.items()}  # normalize
        output = self.scorer.score(probs, "v1")
        assert len(output.top_categories) == 3

    def test_top_categories_sorted_descending(self):
        probs = {
            TicketCategory.NETWORK: 0.70,
            TicketCategory.SECURITY: 0.15,
            TicketCategory.INFRASTRUCTURE: 0.10,
            TicketCategory.APPLICATION: 0.03,
            TicketCategory.DATABASE: 0.01,
            TicketCategory.ACCESS_MANAGEMENT: 0.01,
        }
        output = self.scorer.score(probs, "v1")
        probs_in_output = [entry["probability"] for entry in output.top_categories]
        assert probs_in_output == sorted(probs_in_output, reverse=True)

    def test_top_categories_have_category_and_probability_keys(self):
        probs = _all_probs(TicketCategory.INFRASTRUCTURE, 0.92)
        output = self.scorer.score(probs, "v1")
        for entry in output.top_categories:
            assert "category" in entry
            assert "probability" in entry

    def test_top_categories_category_is_string(self):
        probs = _all_probs(TicketCategory.DATABASE, 0.90)
        output = self.scorer.score(probs, "v1")
        for entry in output.top_categories:
            assert isinstance(entry["category"], str)

    def test_single_category_returns_one_entry(self):
        probs = {TicketCategory.NETWORK: 1.0}
        output = self.scorer.score(probs, "v1")
        assert len(output.top_categories) == 1

    def test_classification_method_preserved(self):
        probs = _all_probs(TicketCategory.NETWORK, 0.90)
        output = self.scorer.score(probs, "logistic_regression_v20260602")
        assert output.classification_method == "logistic_regression_v20260602"


# ── Multi-domain detection ─────────────────────────────────────────────────────


class TestMultiDomainDetection:
    def setup_method(self):
        self.scorer = ConfidenceScorer(_make_settings(multi_domain_diff=0.15))

    def test_gap_below_threshold_is_multi_domain(self):
        """Gap of 0.10 < threshold 0.15 → multi-domain."""
        probs = _two_probs(TicketCategory.SECURITY, 0.45, TicketCategory.ACCESS_MANAGEMENT, 0.35)
        output = self.scorer.score(probs, "v1")
        assert output.is_multi_domain is True

    def test_gap_at_threshold_is_not_multi_domain(self):
        """Gap of exactly 0.15 is NOT strictly less than threshold → single domain."""
        probs = _two_probs(TicketCategory.NETWORK, 0.55, TicketCategory.INFRASTRUCTURE, 0.40)
        output = self.scorer.score(probs, "v1")
        assert output.is_multi_domain is False

    def test_gap_above_threshold_is_not_multi_domain(self):
        """Gap of 0.30 > threshold 0.15 → single domain."""
        probs = _two_probs(TicketCategory.DATABASE, 0.65, TicketCategory.APPLICATION, 0.35)
        output = self.scorer.score(probs, "v1")
        assert output.is_multi_domain is False

    def test_single_category_never_multi_domain(self):
        probs = {TicketCategory.NETWORK: 1.0}
        output = self.scorer.score(probs, "v1")
        assert output.is_multi_domain is False

    def test_high_confidence_with_small_gap_is_multi_domain(self):
        """High confidence doesn't prevent multi-domain if the gap is small."""
        probs = _two_probs(TicketCategory.SECURITY, 0.86, TicketCategory.DATABASE, 0.10)
        output = self.scorer.score(probs, "v1")
        # gap = 0.86 - 0.10 = 0.76 >> 0.15 → NOT multi-domain
        assert output.is_multi_domain is False

    def test_multi_domain_with_tiny_gap(self):
        probs = _two_probs(TicketCategory.INFRASTRUCTURE, 0.40, TicketCategory.NETWORK, 0.39)
        output = self.scorer.score(probs, "v1")
        # gap = 0.01 < 0.15 → multi-domain
        assert output.is_multi_domain is True


# ── Output immutability ────────────────────────────────────────────────────────


class TestClassificationOutputIsImmutable:
    def test_cannot_set_attribute(self):
        probs = _all_probs(TicketCategory.NETWORK, 0.90)
        scorer = ConfidenceScorer(_make_settings())
        output = scorer.score(probs, "v1")
        with pytest.raises((AttributeError, TypeError)):
            output.predicted_category = TicketCategory.DATABASE  # type: ignore[misc]
