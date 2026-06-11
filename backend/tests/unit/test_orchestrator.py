"""Unit tests for TicketOrchestrator (src/agents/orchestrator.py).

All AutoGen agents are mocked — no real AG2 calls or DB operations.
Tests focus on flow control, status transitions, and error recovery.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.orchestrator import TicketOrchestrator
from src.classification.confidence import ClassificationOutput, ConfidenceLevel
from src.db.models import RoutingDecision, TicketCategory, TicketStatus
from src.routing.escalation import EscalationContext
from src.routing.router import RoutingResult


# ── Helpers ───────────────────────────────────────────────────────────────────


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_ticket(ticket_id: uuid.UUID | None = None) -> MagicMock:
    t = MagicMock()
    t.id = ticket_id or _uuid()
    t.title = "VPN authentication failure"
    t.description = "Users cannot connect via VPN."
    t.status = TicketStatus.NEW
    return t


def _classification_msg(ticket_id: uuid.UUID, category: str = "network") -> dict:
    return {
        "type": "CLASSIFICATION_RESULT",
        "ticket_id": str(ticket_id),
        "predicted_category": category,
        "confidence": 0.91,
        "confidence_level": "high",
        "is_multi_domain": False,
        "top_categories": [{"category": category, "probability": 0.91}],
        "classification_method": "logistic_regression_v1",
    }


def _rag_msg(ticket_id: uuid.UUID) -> dict:
    return {
        "type": "RESOLUTION_GENERATED",
        "ticket_id": str(ticket_id),
        "resolution_text": "Step 1: Restart VPN service.",
        "retrieved_entries": [],
    }


def _eval_msg(ticket_id: uuid.UUID, score: float = 4.0) -> dict:
    return {
        "type": "EVALUATION_RESULT",
        "ticket_id": str(ticket_id),
        "quality_score": score,
        "dimension_scores": {"relevance": score, "completeness": score, "actionability": score},
    }


def _error_msg(ticket_id: uuid.UUID, error_code: str = "CLASSIFICATION_ERROR") -> dict:
    return {
        "type": "ERROR",
        "ticket_id": str(ticket_id),
        "error_code": error_code,
        "message": "Something went wrong",
    }


def _make_orchestrator(
    ticket: MagicMock,
    classifier_reply: dict,
    rag_reply: dict,
    eval_reply: dict,
    routing_decision: RoutingDecision = RoutingDecision.AUTO_RESOLVED,
    is_repeated: bool = False,
) -> TicketOrchestrator:
    """Build a TicketOrchestrator with all dependencies mocked."""
    ticket_repo = AsyncMock()
    ticket_repo.get_by_id.return_value = ticket
    ticket_repo.update_status = AsyncMock()

    resolution_repo = AsyncMock()
    persisted_resolution = MagicMock()
    persisted_resolution.routing_decision = routing_decision
    resolution_repo.create.return_value = persisted_resolution

    proxy = MagicMock()

    # Agents — orchestrator calls _classify/_run_rag/_evaluate directly (async)
    classifier_agent = MagicMock()
    classifier_agent.name = "ClassifierAgent"
    classifier_agent._classify = AsyncMock(return_value=classifier_reply)

    rag_agent = MagicMock()
    rag_agent.name = "RAGAgent"
    rag_agent._run_rag = AsyncMock(return_value=rag_reply)

    evaluator_agent = MagicMock()
    evaluator_agent.name = "EvaluatorAgent"
    evaluator_agent._evaluate = AsyncMock(return_value=eval_reply)

    # Router
    router = MagicMock()
    routing_result = RoutingResult(
        decision=routing_decision,
        assigned_department="network-team" if routing_decision != RoutingDecision.ESCALATED else None,
        escalation_reason=None if routing_decision != RoutingDecision.ESCALATED else "test escalation",
    )
    router.decide.return_value = routing_result

    # Escalation detector
    escalation_detector = AsyncMock()
    escalation_detector.check.return_value = EscalationContext(
        is_repeated_issue=is_repeated,
        recurrence_count=5 if is_repeated else 0,
        automation_suggestion="Consider automation." if is_repeated else None,
    )

    return TicketOrchestrator(
        classifier_agent=classifier_agent,
        rag_agent=rag_agent,
        evaluator_agent=evaluator_agent,
        proxy=proxy,
        router=router,
        escalation_detector=escalation_detector,
        ticket_repo=ticket_repo,
        resolution_repo=resolution_repo,
    )


# ── Normal flow ───────────────────────────────────────────────────────────────


class TestNormalFlow:
    async def test_process_ticket_returns_resolution(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_classification_msg(ticket_id),
            rag_reply=_rag_msg(ticket_id),
            eval_reply=_eval_msg(ticket_id),
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            resolution = await orch.process_ticket(ticket_id)

        assert resolution is not None

    async def test_all_three_agents_called_in_order(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_classification_msg(ticket_id),
            rag_reply=_rag_msg(ticket_id),
            eval_reply=_eval_msg(ticket_id),
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            await orch.process_ticket(ticket_id)

        # Orchestrator calls agents directly (not via proxy.initiate_chat)
        orch._classifier_agent._classify.assert_called_once()
        orch._rag_agent._run_rag.assert_called_once()
        orch._evaluator_agent._evaluate.assert_called_once()

    async def test_status_transitions_to_classifying(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_classification_msg(ticket_id),
            rag_reply=_rag_msg(ticket_id),
            eval_reply=_eval_msg(ticket_id),
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            await orch.process_ticket(ticket_id)

        status_calls = [call.args[1] for call in orch._ticket_repo.update_status.call_args_list]
        assert TicketStatus.CLASSIFYING in status_calls

    async def test_resolution_persisted_via_repo(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_classification_msg(ticket_id),
            rag_reply=_rag_msg(ticket_id),
            eval_reply=_eval_msg(ticket_id),
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            await orch.process_ticket(ticket_id)

        orch._resolution_repo.create.assert_called_once()

    async def test_repeated_issue_flag_set_on_resolution(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_classification_msg(ticket_id),
            rag_reply=_rag_msg(ticket_id),
            eval_reply=_eval_msg(ticket_id),
            is_repeated=True,
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            await orch.process_ticket(ticket_id)

        create_call = orch._resolution_repo.create.call_args.args[0]
        assert create_call.is_repeated_issue is True


# ── Error recovery ────────────────────────────────────────────────────────────


class TestErrorRecovery:
    async def test_classifier_error_creates_escalated_resolution(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_error_msg(ticket_id, "CLASSIFICATION_ERROR"),
            rag_reply=_rag_msg(ticket_id),   # should NOT be called
            eval_reply=_eval_msg(ticket_id), # should NOT be called
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            await orch.process_ticket(ticket_id)

        create_call = orch._resolution_repo.create.call_args.args[0]
        assert create_call.routing_decision == RoutingDecision.ESCALATED

    async def test_classifier_error_skips_rag_and_evaluator(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_error_msg(ticket_id),
            rag_reply=_rag_msg(ticket_id),
            eval_reply=_eval_msg(ticket_id),
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            await orch.process_ticket(ticket_id)

        # Only ClassifierAgent should have been called
        calls = [call.args[0].name for call in orch._proxy.initiate_chat.call_args_list]
        assert "RAGAgent" not in calls
        assert "EvaluatorAgent" not in calls

    async def test_rag_error_creates_escalated_resolution(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_classification_msg(ticket_id),
            rag_reply=_error_msg(ticket_id, "LLM_UNAVAILABLE"),
            eval_reply=_eval_msg(ticket_id),
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            await orch.process_ticket(ticket_id)

        create_call = orch._resolution_repo.create.call_args.args[0]
        assert create_call.routing_decision == RoutingDecision.ESCALATED

    async def test_rag_error_skips_evaluator(self):
        ticket_id = _uuid()
        ticket = _make_ticket(ticket_id)
        orch = _make_orchestrator(
            ticket=ticket,
            classifier_reply=_classification_msg(ticket_id),
            rag_reply=_error_msg(ticket_id, "LLM_UNAVAILABLE"),
            eval_reply=_eval_msg(ticket_id),
        )
        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            await orch.process_ticket(ticket_id)

        calls = [call.args[0].name for call in orch._proxy.initiate_chat.call_args_list]
        assert "EvaluatorAgent" not in calls


# ── Ticket not found ──────────────────────────────────────────────────────────


class TestTicketNotFound:
    async def test_missing_ticket_raises_not_found_error(self):
        from src.core.exceptions import TicketNotFoundError

        ticket_repo = AsyncMock()
        ticket_repo.get_by_id.return_value = None

        orch = TicketOrchestrator(
            classifier_agent=MagicMock(),
            rag_agent=MagicMock(),
            evaluator_agent=MagicMock(),
            proxy=MagicMock(),
            router=MagicMock(),
            escalation_detector=AsyncMock(),
            ticket_repo=ticket_repo,
            resolution_repo=AsyncMock(),
        )
        with pytest.raises(TicketNotFoundError):
            await orch.process_ticket(uuid.uuid4())
