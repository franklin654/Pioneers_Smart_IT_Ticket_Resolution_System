import pytest
from pydantic import ValidationError as PydanticValidationError

from src.db.models import (
    TERMINAL_TICKET_STATUSES,
    ResolutionStep,
    RoutingDecision,
    TicketCategory,
    TicketStatus,
)


def test_resolution_step_accepts_valid_input() -> None:
    step = ResolutionStep(step_number=1, instruction="Restart the affected service.")
    assert step.step_number == 1
    assert step.instruction == "Restart the affected service."


@pytest.mark.parametrize("step_number", [0, -1])
def test_resolution_step_rejects_non_positive_step_number(step_number: int) -> None:
    with pytest.raises(PydanticValidationError):
        ResolutionStep(step_number=step_number, instruction="x")


def test_resolution_step_rejects_empty_instruction() -> None:
    with pytest.raises(PydanticValidationError):
        ResolutionStep(step_number=1, instruction="")


def test_awaiting_review_is_explicitly_not_terminal() -> None:
    """The whole point of the v2 pre-generation gate — see
    docs/02_ARCHITECTURE.md — is that AWAITING_REVIEW resumes, it doesn't end."""
    assert TicketStatus.AWAITING_REVIEW not in TERMINAL_TICKET_STATUSES


def test_terminal_statuses_are_exactly_the_documented_four() -> None:
    assert TERMINAL_TICKET_STATUSES == {
        TicketStatus.AUTO_RESOLVED,
        TicketStatus.ASSIGNED,
        TicketStatus.ESCALATED,
        TicketStatus.CLOSED,
    }


def test_ticket_category_has_exactly_six_values() -> None:
    assert len(TicketCategory) == 6


def test_routing_decision_has_a_distinct_awaiting_review_value() -> None:
    assert RoutingDecision.AWAITING_REVIEW.value == "awaiting_review"
    assert RoutingDecision.AWAITING_REVIEW != RoutingDecision.ESCALATED
