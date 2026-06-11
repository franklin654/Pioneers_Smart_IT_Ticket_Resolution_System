"""Unit tests for TicketRouter (src/routing/router.py).

Pure Python — no DB, no LLM, no mocks needed.
"""

from __future__ import annotations

import pytest

from src.classification.confidence import ClassificationOutput, ConfidenceLevel
from src.db.models import RoutingDecision, TicketCategory
from src.routing.router import RoutingResult, TicketRouter, _DEPARTMENT_MAP, _LLM_QUALITY_THRESHOLD


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_output(
    category: TicketCategory = TicketCategory.NETWORK,
    confidence: float = 0.90,
    confidence_level: ConfidenceLevel = ConfidenceLevel.HIGH,
    is_multi_domain: bool = False,
) -> ClassificationOutput:
    return ClassificationOutput(
        predicted_category=category,
        confidence=confidence,
        confidence_level=confidence_level,
        top_categories=[{"category": category.value, "probability": confidence}],
        is_multi_domain=is_multi_domain,
        classification_method="logistic_regression_v1",
    )


router = TicketRouter()


# ── Happy path: AUTO_RESOLVED ─────────────────────────────────────────────────


class TestAutoResolved:
    def test_high_confidence_good_quality_auto_resolved(self):
        result = router.decide(_make_output(confidence_level=ConfidenceLevel.HIGH), 4.0)
        assert result.decision == RoutingDecision.AUTO_RESOLVED

    def test_auto_resolved_has_department(self):
        result = router.decide(_make_output(category=TicketCategory.NETWORK), 4.0)
        assert result.assigned_department == "network-team"

    def test_auto_resolved_no_escalation_reason(self):
        result = router.decide(_make_output(), 4.0)
        assert result.escalation_reason is None

    def test_quality_exactly_at_threshold_not_escalated(self):
        result = router.decide(_make_output(confidence_level=ConfidenceLevel.HIGH), _LLM_QUALITY_THRESHOLD)
        assert result.decision == RoutingDecision.AUTO_RESOLVED


# ── Happy path: ASSIGNED ──────────────────────────────────────────────────────


class TestAssigned:
    def test_medium_confidence_good_quality_assigned(self):
        result = router.decide(
            _make_output(confidence=0.72, confidence_level=ConfidenceLevel.MEDIUM),
            4.0,
        )
        assert result.decision == RoutingDecision.ASSIGNED

    def test_assigned_has_department(self):
        result = router.decide(
            _make_output(category=TicketCategory.DATABASE, confidence_level=ConfidenceLevel.MEDIUM),
            4.0,
        )
        assert result.assigned_department == "database-team"

    def test_assigned_no_escalation_reason(self):
        result = router.decide(
            _make_output(confidence_level=ConfidenceLevel.MEDIUM), 4.0
        )
        assert result.escalation_reason is None


# ── Escalation: Rule 1 — multi-domain ─────────────────────────────────────────


class TestEscalateMultiDomain:
    def test_multi_domain_always_escalates(self):
        result = router.decide(_make_output(is_multi_domain=True), 5.0)
        assert result.decision == RoutingDecision.ESCALATED

    def test_multi_domain_overrides_high_confidence(self):
        result = router.decide(
            _make_output(confidence=0.95, confidence_level=ConfidenceLevel.HIGH, is_multi_domain=True),
            5.0,
        )
        assert result.decision == RoutingDecision.ESCALATED

    def test_multi_domain_reason_set(self):
        result = router.decide(_make_output(is_multi_domain=True), 5.0)
        assert result.escalation_reason is not None
        assert "multi-domain" in result.escalation_reason.lower() or "specialist" in result.escalation_reason.lower()

    def test_multi_domain_no_department(self):
        result = router.decide(_make_output(is_multi_domain=True), 5.0)
        assert result.assigned_department is None


# ── Escalation: Rule 2 — low confidence ───────────────────────────────────────


class TestEscalateLowConfidence:
    def test_low_confidence_escalates(self):
        result = router.decide(
            _make_output(confidence=0.45, confidence_level=ConfidenceLevel.LOW),
            5.0,
        )
        assert result.decision == RoutingDecision.ESCALATED

    def test_low_confidence_escalates_even_with_good_quality(self):
        result = router.decide(
            _make_output(confidence=0.30, confidence_level=ConfidenceLevel.LOW),
            5.0,
        )
        assert result.decision == RoutingDecision.ESCALATED

    def test_low_confidence_reason_contains_score(self):
        result = router.decide(
            _make_output(confidence=0.42, confidence_level=ConfidenceLevel.LOW),
            5.0,
        )
        assert "0.42" in result.escalation_reason


# ── Escalation: Rule 3 — poor LLM quality ────────────────────────────────────


class TestEscalateLLMQuality:
    def test_quality_below_threshold_escalates(self):
        result = router.decide(
            _make_output(confidence_level=ConfidenceLevel.HIGH),
            2.0,
        )
        assert result.decision == RoutingDecision.ESCALATED

    def test_zero_quality_escalates(self):
        result = router.decide(_make_output(), 0.0)
        assert result.decision == RoutingDecision.ESCALATED

    def test_medium_confidence_poor_quality_escalates(self):
        result = router.decide(
            _make_output(confidence_level=ConfidenceLevel.MEDIUM),
            1.5,
        )
        assert result.decision == RoutingDecision.ESCALATED

    def test_quality_just_below_threshold_escalates(self):
        result = router.decide(
            _make_output(confidence_level=ConfidenceLevel.HIGH),
            _LLM_QUALITY_THRESHOLD - 0.01,
        )
        assert result.decision == RoutingDecision.ESCALATED

    def test_quality_reason_contains_score(self):
        result = router.decide(_make_output(confidence_level=ConfidenceLevel.HIGH), 2.8)
        assert "2.8" in result.escalation_reason


# ── Department mapping ────────────────────────────────────────────────────────


class TestDepartmentMapping:
    @pytest.mark.parametrize("category,expected_dept", [
        (TicketCategory.INFRASTRUCTURE, "infrastructure-team"),
        (TicketCategory.APPLICATION, "application-team"),
        (TicketCategory.SECURITY, "security-team"),
        (TicketCategory.DATABASE, "database-team"),
        (TicketCategory.ACCESS_MANAGEMENT, "iam-team"),
        (TicketCategory.NETWORK, "network-team"),
    ])
    def test_department_map_all_categories(self, category, expected_dept):
        result = router.decide(
            _make_output(category=category, confidence_level=ConfidenceLevel.HIGH),
            4.0,
        )
        assert result.assigned_department == expected_dept

    def test_all_categories_covered_in_map(self):
        for cat in TicketCategory:
            assert cat in _DEPARTMENT_MAP, f"Missing department for {cat.value}"

    def test_result_is_immutable(self):
        result = router.decide(_make_output(), 4.0)
        assert isinstance(result, RoutingResult)
        with pytest.raises((AttributeError, TypeError)):
            result.decision = RoutingDecision.ESCALATED  # type: ignore[misc]
