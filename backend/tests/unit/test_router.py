"""Unit tests for all 5 TicketRouter rules and EscalationDetector (Phase 5 gate)."""

from __future__ import annotations

import pytest

from src.classification.classifier import ClassificationOutput
from src.db.models import RoutingDecision, TicketCategory
from src.routing.escalation import EscalationDetector
from src.routing.router import TicketRouter


def _classification(
    category: TicketCategory = TicketCategory.DATABASE,
    confidence: float = 0.90,
    confidence_level: str = "high",
    is_multi_domain: bool = False,
    top2_gap: float = 0.80,
) -> ClassificationOutput:
    return ClassificationOutput(
        category=category,
        confidence=confidence,
        confidence_level=confidence_level,
        is_multi_domain=is_multi_domain,
        top2_gap=top2_gap,
        classification_method="tfidf_svm_calibrated",
        all_probabilities={category.value: confidence},
    )


QUALITY_THRESHOLD = 3.5
router = TicketRouter(quality_threshold=QUALITY_THRESHOLD)


# ---------------------------------------------------------------------------
# Pre-generation gate: rules 1 & 2
# ---------------------------------------------------------------------------


def test_rule1_multi_domain_triggers_awaiting_review() -> None:
    clf = _classification(is_multi_domain=True, confidence_level="high", top2_gap=0.05)
    result = router.pre_generation_check(clf)
    assert result is not None
    assert result.decision == RoutingDecision.AWAITING_REVIEW


def test_rule2_low_confidence_triggers_awaiting_review() -> None:
    clf = _classification(confidence=0.45, confidence_level="low", is_multi_domain=False)
    result = router.pre_generation_check(clf)
    assert result is not None
    assert result.decision == RoutingDecision.AWAITING_REVIEW


def test_pre_check_returns_none_for_high_confidence_single_domain() -> None:
    clf = _classification(confidence=0.90, confidence_level="high", is_multi_domain=False)
    assert router.pre_generation_check(clf) is None


def test_pre_check_returns_none_for_medium_confidence_single_domain() -> None:
    clf = _classification(confidence=0.72, confidence_level="medium", is_multi_domain=False)
    assert router.pre_generation_check(clf) is None


# ---------------------------------------------------------------------------
# Post-generation routing: rules 3, 4, 5
# ---------------------------------------------------------------------------


def test_rule3_low_quality_score_escalates() -> None:
    clf = _classification(confidence=0.92, confidence_level="high")
    result = router.decide(clf, llm_quality_score=2.8)
    assert result.decision == RoutingDecision.ESCALATED


def test_rule3_score_at_threshold_does_not_escalate() -> None:
    clf = _classification(confidence=0.92, confidence_level="high")
    result = router.decide(clf, llm_quality_score=QUALITY_THRESHOLD)
    assert result.decision != RoutingDecision.ESCALATED


def test_rule4_high_confidence_good_score_auto_resolves() -> None:
    clf = _classification(confidence=0.92, confidence_level="high")
    result = router.decide(clf, llm_quality_score=4.0)
    assert result.decision == RoutingDecision.AUTO_RESOLVED


def test_rule5_medium_confidence_good_score_assigns() -> None:
    clf = _classification(confidence=0.72, confidence_level="medium")
    result = router.decide(clf, llm_quality_score=4.0)
    assert result.decision == RoutingDecision.ASSIGNED


# Rules 1 & 2 must also fire inside decide() (single source of truth)
def test_decide_also_applies_rule1_multi_domain() -> None:
    clf = _classification(is_multi_domain=True, top2_gap=0.05, confidence_level="high")
    result = router.decide(clf, llm_quality_score=4.5)
    assert result.decision == RoutingDecision.AWAITING_REVIEW


def test_decide_also_applies_rule2_low_confidence() -> None:
    clf = _classification(confidence=0.40, confidence_level="low")
    result = router.decide(clf, llm_quality_score=4.5)
    assert result.decision == RoutingDecision.AWAITING_REVIEW


# ---------------------------------------------------------------------------
# EscalationDetector
# ---------------------------------------------------------------------------


class _FakeTicket:
    def __init__(self, title: str, description: str, priority: int = 3) -> None:
        self.id = "fake-id"
        self.title = title
        self.description = description
        self.priority = priority


def test_escalation_on_outage_keyword() -> None:
    detector = EscalationDetector()
    ticket = _FakeTicket("Production outage", "All services down.")
    reasons: list[str] = []
    assert detector.should_escalate(ticket, reasons) is True  # type: ignore[arg-type]
    assert len(reasons) == 1


def test_escalation_on_high_priority() -> None:
    detector = EscalationDetector()
    ticket = _FakeTicket("Minor UI glitch", "Button color wrong.", priority=1)
    reasons: list[str] = []
    assert detector.should_escalate(ticket, reasons) is True  # type: ignore[arg-type]
    assert "priority" in reasons[0].lower()


def test_no_escalation_for_normal_ticket() -> None:
    detector = EscalationDetector()
    ticket = _FakeTicket("Printer offline", "Printer in meeting room won't print.", priority=4)
    reasons: list[str] = []
    assert detector.should_escalate(ticket, reasons) is False  # type: ignore[arg-type]
    assert reasons == []
