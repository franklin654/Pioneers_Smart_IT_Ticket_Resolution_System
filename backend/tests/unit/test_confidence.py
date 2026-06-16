"""Unit tests for classification/confidence.py."""

import pytest

from src.classification.confidence import score
from src.db.models import TicketCategory


def _probs(**kwargs: float) -> dict[TicketCategory, float]:
    return {TicketCategory(k): v for k, v in kwargs.items()}


def test_high_confidence_clear_winner() -> None:
    probs = _probs(security=0.90, access_management=0.05, network=0.03, application=0.01,
                   database=0.005, infrastructure=0.005)
    result = score(probs, high_threshold=0.85, low_threshold=0.60, multi_domain_diff=0.15)

    assert result.confidence_level == "high"
    assert result.top_category == TicketCategory.SECURITY
    assert result.is_multi_domain is False
    assert result.top2_gap == pytest.approx(0.85, abs=0.01)


def test_medium_confidence() -> None:
    probs = _probs(security=0.75, access_management=0.15, network=0.05, application=0.03,
                   database=0.01, infrastructure=0.01)
    result = score(probs, high_threshold=0.85, low_threshold=0.60, multi_domain_diff=0.15)

    assert result.confidence_level == "medium"
    assert result.is_multi_domain is False


def test_low_confidence() -> None:
    probs = _probs(security=0.50, access_management=0.40, network=0.05, application=0.03,
                   database=0.01, infrastructure=0.01)
    result = score(probs, high_threshold=0.85, low_threshold=0.60, multi_domain_diff=0.15)

    assert result.confidence_level == "low"


def test_multi_domain_detected_when_gap_small() -> None:
    probs = _probs(security=0.52, access_management=0.42, network=0.03, application=0.01,
                   database=0.01, infrastructure=0.01)
    result = score(probs, high_threshold=0.85, low_threshold=0.60, multi_domain_diff=0.15)

    assert result.is_multi_domain is True
    assert result.second_category == TicketCategory.ACCESS_MANAGEMENT
    assert result.top2_gap == pytest.approx(0.10, abs=0.001)


def test_multi_domain_not_detected_when_gap_large() -> None:
    probs = _probs(security=0.90, access_management=0.07, network=0.01, application=0.01,
                   database=0.005, infrastructure=0.005)
    result = score(probs, high_threshold=0.85, low_threshold=0.60, multi_domain_diff=0.15)

    assert result.is_multi_domain is False


def test_boundary_exactly_at_high_threshold() -> None:
    probs = _probs(security=0.85, access_management=0.10, network=0.02, application=0.01,
                   database=0.01, infrastructure=0.01)
    result = score(probs, high_threshold=0.85, low_threshold=0.60, multi_domain_diff=0.15)

    assert result.confidence_level == "high"


def test_boundary_exactly_at_low_threshold() -> None:
    probs = _probs(security=0.60, access_management=0.30, network=0.05, application=0.03,
                   database=0.01, infrastructure=0.01)
    result = score(probs, high_threshold=0.85, low_threshold=0.60, multi_domain_diff=0.15)

    assert result.confidence_level == "medium"


def test_all_probabilities_returned() -> None:
    probs = _probs(security=0.90, access_management=0.05, network=0.03, application=0.01,
                   database=0.005, infrastructure=0.005)
    result = score(probs)

    assert result.top_category == TicketCategory.SECURITY
    assert result.confidence == pytest.approx(0.90)
