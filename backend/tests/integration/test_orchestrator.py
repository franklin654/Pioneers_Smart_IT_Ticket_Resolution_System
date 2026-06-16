"""Integration tests for the TicketOrchestrator (Phase 5 gate).

Tests:
- RAG agent is NOT invoked when confidence is LOW (Rule 2 → AWAITING_REVIEW)
- RAG agent is NOT invoked when is_multi_domain (Rule 1 → AWAITING_REVIEW)
- Full AWAITING_REVIEW → reclassify → terminal status end-to-end
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.classifier_agent import ClassifierAgent
from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.orchestrator import OrchestratorResult, TicketOrchestrator
from src.agents.rag_agent import RAGAgent
from src.classification.classifier import ClassificationOutput
from src.db.models import (
    ClassificationMethod,
    RoutingDecision,
    TicketCategory,
    TicketSource,
    TicketStatus,
)
from src.db.repositories.classification_repo import ClassificationRepository
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.routing.escalation import EscalationDetector
from src.routing.router import TicketRouter


def _make_clf(
    category: TicketCategory = TicketCategory.DATABASE,
    confidence: float = 0.90,
    confidence_level: str = "high",
    is_multi_domain: bool = False,
) -> ClassificationOutput:
    return ClassificationOutput(
        category=category,
        confidence=confidence,
        confidence_level=confidence_level,
        is_multi_domain=is_multi_domain,
        top2_gap=0.05 if is_multi_domain else 0.80,
        classification_method="tfidf_svm_calibrated",
        all_probabilities={category.value: confidence},
    )


def _mock_rag_agent(steps: list | None = None) -> RAGAgent:
    from src.db.models import ResolutionStep

    agent = MagicMock(spec=RAGAgent)
    agent._run_rag = AsyncMock(  # noqa: SLF001
        return_value=(
            steps or [ResolutionStep(step_number=1, instruction="Check logs")],
            [],
        )
    )
    return agent


def _make_orchestrator(
    classifier_output: ClassificationOutput,
    db_session: object,
    *,
    quality_score: float = 4.0,
    rag_agent: RAGAgent | None = None,
) -> tuple[TicketOrchestrator, RAGAgent]:
    clf_agent = MagicMock(spec=ClassifierAgent)
    clf_agent._classify = AsyncMock(return_value=classifier_output)  # noqa: SLF001

    rag = rag_agent or _mock_rag_agent()

    eval_agent = MagicMock(spec=EvaluatorAgent)
    eval_agent._evaluate = AsyncMock(return_value=quality_score)  # noqa: SLF001

    orch = TicketOrchestrator(
        classifier_agent=clf_agent,
        rag_agent=rag,
        evaluator_agent=eval_agent,
        router=TicketRouter(quality_threshold=3.5),
        escalation_detector=EscalationDetector(),
        ticket_repo=TicketRepository(db_session),  # type: ignore[arg-type]
        classification_repo=ClassificationRepository(db_session),  # type: ignore[arg-type]
        resolution_repo=ResolutionRepository(db_session),  # type: ignore[arg-type]
    )
    return orch, rag


# ---------------------------------------------------------------------------
# Gate: RAG must NOT be invoked on pre-generation gate cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_not_invoked_when_confidence_low(db_session) -> None:
    clf_out = _make_clf(confidence=0.40, confidence_level="low")
    ticket = await TicketRepository(db_session).create(
        title="Low confidence ticket",
        description="Something vague happened.",
        original_description="Something vague happened.",
        priority=3,
        status=TicketStatus.NEW,
        source=TicketSource.API,
        pii_detected=False,
        content_hash="hash-low-conf",
    )

    orch, rag = _make_orchestrator(clf_out, db_session)
    result = await orch.run(ticket)

    assert result.routing_decision == RoutingDecision.AWAITING_REVIEW
    rag._run_rag.assert_not_called()  # noqa: SLF001


@pytest.mark.asyncio
async def test_rag_not_invoked_when_multi_domain(db_session) -> None:
    clf_out = _make_clf(is_multi_domain=True, confidence_level="high")
    ticket = await TicketRepository(db_session).create(
        title="Multi-domain ticket",
        description="Network and security issue combined.",
        original_description="Network and security issue combined.",
        priority=3,
        status=TicketStatus.NEW,
        source=TicketSource.API,
        pii_detected=False,
        content_hash="hash-multi-domain",
    )

    orch, rag = _make_orchestrator(clf_out, db_session)
    result = await orch.run(ticket)

    assert result.routing_decision == RoutingDecision.AWAITING_REVIEW
    rag._run_rag.assert_not_called()  # noqa: SLF001


# ---------------------------------------------------------------------------
# Gate: AWAITING_REVIEW → reclassify → terminal status end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reclassification_resumes_pipeline_to_terminal_status(db_session) -> None:
    # 1. First pass: low confidence → AWAITING_REVIEW
    clf_low = _make_clf(confidence=0.40, confidence_level="low")
    ticket = await TicketRepository(db_session).create(
        title="Ambiguous ticket",
        description="Something is broken, not sure where.",
        original_description="Something is broken, not sure where.",
        priority=3,
        status=TicketStatus.NEW,
        source=TicketSource.API,
        pii_detected=False,
        content_hash="hash-reclassify-e2e",
    )

    orch_first, _ = _make_orchestrator(clf_low, db_session)
    first_result = await orch_first.run(ticket)
    assert first_result.routing_decision == RoutingDecision.AWAITING_REVIEW

    # Verify DB status is AWAITING_REVIEW
    repo = TicketRepository(db_session)
    refreshed = await repo.get_by_id(ticket.id)
    assert refreshed is not None
    assert refreshed.status == TicketStatus.AWAITING_REVIEW

    # 2. Human reclassifies → resume
    human_category = TicketCategory.INFRASTRUCTURE
    clf_high = _make_clf(category=human_category, confidence=1.0, confidence_level="high")
    orch_resume, rag_resume = _make_orchestrator(clf_high, db_session, quality_score=4.2)
    # Override classifier to return high confidence so resume goes terminal
    orch_resume._classifier_agent._classify = AsyncMock(return_value=clf_high)  # noqa: SLF001

    resume_result = await orch_resume.resume_after_reclassification(refreshed, human_category)

    assert resume_result.routing_decision in {
        RoutingDecision.AUTO_RESOLVED,
        RoutingDecision.ASSIGNED,
    }
    rag_resume._run_rag.assert_called_once()  # noqa: SLF001

    final = await repo.get_by_id(ticket.id)
    assert final is not None
    assert final.status in {TicketStatus.AUTO_RESOLVED, TicketStatus.ASSIGNED}
