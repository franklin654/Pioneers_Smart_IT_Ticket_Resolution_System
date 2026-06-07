"""Unit tests for Pydantic v2 API schemas (src/schemas/).

All tests are pure Python — no database or network calls.
"""

import uuid

import pytest
from pydantic import ValidationError

from src.db.models import FeedbackAction, RoutingDecision, TicketCategory, TicketStatus, TicketSource
from src.schemas.classification import CategoryProbability, ClassificationResponse
from src.schemas.resolution import FeedbackRequest, ResolutionResponse
from src.schemas.ticket import (
    PaginatedTicketsResponse,
    TicketDetailResponse,
    TicketIngestRequest,
    TicketIngestResponse,
    TicketSummary,
)


# ── TicketIngestRequest ───────────────────────────────────────────────────────


class TestTicketIngestRequest:
    def test_valid_minimal_ticket(self):
        req = TicketIngestRequest(
            title="VPN is down",
            description="Cannot connect to corporate VPN from home office.",
            priority=2,
        )
        assert req.title == "VPN is down"
        assert req.category is None

    def test_valid_ticket_with_category(self):
        req = TicketIngestRequest(
            title="DB query timeout",
            description="Production database queries are timing out after 30 seconds.",
            priority=1,
            category=TicketCategory.DATABASE,
        )
        assert req.category == TicketCategory.DATABASE

    def test_title_too_short_raises(self):
        with pytest.raises(ValidationError):
            TicketIngestRequest(title="ab", description="valid description here", priority=3)

    def test_title_too_long_raises(self):
        with pytest.raises(ValidationError):
            TicketIngestRequest(title="x" * 201, description="valid description here", priority=3)

    def test_description_too_short_raises(self):
        with pytest.raises(ValidationError):
            TicketIngestRequest(title="Valid Title", description="short", priority=3)

    def test_description_too_long_raises(self):
        with pytest.raises(ValidationError):
            TicketIngestRequest(title="Valid Title", description="x" * 5001, priority=3)

    def test_priority_zero_raises(self):
        with pytest.raises(ValidationError):
            TicketIngestRequest(
                title="Valid Title", description="valid description here", priority=0
            )

    def test_priority_six_raises(self):
        with pytest.raises(ValidationError):
            TicketIngestRequest(
                title="Valid Title", description="valid description here", priority=6
            )

    @pytest.mark.parametrize("priority", [1, 2, 3, 4, 5])
    def test_all_valid_priorities_accepted(self, priority):
        req = TicketIngestRequest(
            title="Valid Title", description="valid description here", priority=priority
        )
        assert req.priority == priority

    def test_whitespace_stripped_from_title(self):
        req = TicketIngestRequest(
            title="  VPN   Down  ",
            description="Cannot connect to VPN from home.",
            priority=3,
        )
        assert req.title == "VPN Down"

    def test_internal_whitespace_normalized(self):
        req = TicketIngestRequest(
            title="Server  Issue",
            description="The   server   is   down   and   not   responding.",
            priority=2,
        )
        assert "  " not in req.description

    def test_all_six_categories_accepted(self):
        for cat in TicketCategory:
            req = TicketIngestRequest(
                title="Test ticket",
                description="A valid description long enough to pass validation.",
                priority=3,
                category=cat,
            )
            assert req.category == cat


# ── FeedbackRequest ───────────────────────────────────────────────────────────


class TestFeedbackRequest:
    def test_accepted_requires_no_resolution(self):
        req = FeedbackRequest(action=FeedbackAction.ACCEPTED)
        assert req.modified_resolution is None

    def test_rejected_requires_no_resolution(self):
        req = FeedbackRequest(action=FeedbackAction.REJECTED)
        assert req.modified_resolution is None

    def test_modified_without_resolution_raises(self):
        with pytest.raises(ValidationError, match="modified_resolution is required"):
            FeedbackRequest(action=FeedbackAction.MODIFIED)

    def test_modified_with_empty_string_raises(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(action=FeedbackAction.MODIFIED, modified_resolution="")

    def test_modified_with_resolution_succeeds(self):
        req = FeedbackRequest(
            action=FeedbackAction.MODIFIED,
            modified_resolution="Step 1: Restart the service.",
        )
        assert req.modified_resolution == "Step 1: Restart the service."


# ── ClassificationResponse ────────────────────────────────────────────────────


class TestClassificationResponse:
    def test_from_orm_dict(self):
        """Verify from_attributes=True allows constructing from ORM-like object."""
        from types import SimpleNamespace
        from src.db.models import ConfidenceLevel

        orm_obj = SimpleNamespace(
            predicted_category=TicketCategory.NETWORK,
            confidence=0.91,
            confidence_level=ConfidenceLevel.HIGH,
            top_categories=[{"category": "network", "probability": 0.91}],
            is_multi_domain=False,
            classification_method="logistic_regression_v1",
        )
        resp = ClassificationResponse.model_validate(orm_obj)
        assert resp.predicted_category == TicketCategory.NETWORK
        assert resp.confidence == 0.91


# ── ResolutionResponse ────────────────────────────────────────────────────────


class TestResolutionResponse:
    def test_escalated_resolution_has_no_steps(self):
        resp = ResolutionResponse(
            id=uuid.uuid4(),
            suggested_steps=None,
            retrieved_tickets=None,
            llm_quality_score=None,
            routing_decision=RoutingDecision.ESCALATED,
            assigned_department=None,
            escalation_reason="Low confidence and multi-domain ticket",
            is_repeated_issue=False,
        )
        assert resp.suggested_steps is None
        assert resp.escalation_reason is not None

    def test_auto_resolved_has_quality_score(self):
        resp = ResolutionResponse(
            id=uuid.uuid4(),
            suggested_steps="Step 1: Restart the VPN client.",
            retrieved_tickets=[],
            llm_quality_score=4.2,
            routing_decision=RoutingDecision.AUTO_RESOLVED,
            assigned_department=None,
            escalation_reason=None,
            is_repeated_issue=False,
        )
        assert resp.llm_quality_score == 4.2
        assert resp.routing_decision == RoutingDecision.AUTO_RESOLVED
