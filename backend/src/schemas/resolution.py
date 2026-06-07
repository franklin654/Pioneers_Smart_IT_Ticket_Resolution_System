"""Pydantic v2 schemas for resolution responses and feedback requests."""

import uuid

from pydantic import BaseModel, ConfigDict, model_validator

from src.db.models import FeedbackAction, RoutingDecision


class RetrievedTicketRef(BaseModel):
    """Lightweight reference to a knowledge base entry used during retrieval."""

    entry_id: str
    title: str
    similarity_score: float


class ResolutionResponse(BaseModel):
    """Full resolution data returned to API consumers.

    Attributes:
        id: UUID of the resolution record.
        suggested_steps: LLM-generated step-by-step resolution (may be
            ``None`` for escalated tickets where LLM was not invoked).
        retrieved_tickets: Knowledge base entries used to generate the
            resolution, with their similarity scores.
        llm_quality_score: LLM-as-judge composite score (0–5); ``None``
            when the ticket was escalated before generation.
        routing_decision: Final routing outcome.
        assigned_department: Target department queue (set when decision is
            ``ASSIGNED``).
        escalation_reason: Human-readable reason for escalation (set when
            decision is ``ESCALATED``).
        is_repeated_issue: ``True`` when a similar ticket was seen within the
            past 30 days, flagging a potential automation candidate.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suggested_steps: str | None
    retrieved_tickets: list[RetrievedTicketRef] | None
    llm_quality_score: float | None
    routing_decision: RoutingDecision
    assigned_department: str | None
    escalation_reason: str | None
    is_repeated_issue: bool


class FeedbackRequest(BaseModel):
    """Payload for submitting agent feedback on a resolution.

    Attributes:
        action: What the agent did with the suggestion.
        modified_resolution: Required when ``action`` is ``MODIFIED``;
            contains the corrected resolution text that will be added to
            the knowledge base.
    """

    action: FeedbackAction
    modified_resolution: str | None = None

    @model_validator(mode="after")
    def modified_resolution_required_for_modified_action(self) -> "FeedbackRequest":
        """Enforce that a modified resolution is provided when action is MODIFIED."""
        if self.action == FeedbackAction.MODIFIED and not self.modified_resolution:
            raise ValueError(
                "modified_resolution is required when action is 'modified'"
            )
        return self
