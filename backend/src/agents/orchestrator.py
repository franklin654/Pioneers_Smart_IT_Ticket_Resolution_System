"""TicketOrchestrator — sequential multi-agent pipeline coordinator.

Drives a ticket through four stages using two-agent AutoGen chats:

    1. Proxy → ClassifierAgent   (CLASSIFY → CLASSIFICATION_RESULT)
    2. Proxy → RAGAgent          (RETRIEVE_AND_GENERATE → RESOLUTION_GENERATED)
    3. Proxy → EvaluatorAgent    (EVALUATE → EVALUATION_RESULT)
    4. EscalationDetector + TicketRouter → persist Resolution

Each stage is a separate ``initiate_chat`` call (max_turns=1) so the
orchestrator keeps full control of the flow.  AutoGen's synchronous
``initiate_chat`` is run inside ``asyncio.to_thread`` so it never blocks
the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

from src.classification.confidence import ClassificationOutput, ConfidenceLevel
from src.core.exceptions import TicketNotFoundError
from src.core.logging import get_logger
from src.db.models import (
    Classification,
    Resolution,
    RoutingDecision,
    TicketCategory,
    TicketStatus,
)
from src.routing.router import RoutingResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.agents.classifier_agent import ClassifierAgent
    from src.agents.evaluator_agent import EvaluatorAgent
    from src.agents.rag_agent import RAGAgent
    from src.agents.user_proxy import TicketUserProxy
    from src.core.config import Settings
    from src.db.repositories.resolution_repo import ResolutionRepository
    from src.db.repositories.ticket_repo import TicketRepository
    from src.routing.escalation import EscalationDetector
    from src.routing.router import TicketRouter

logger = get_logger(__name__)


class TicketOrchestrator:
    """Coordinates the full ticket processing pipeline via AutoGen agents.

    Sequential flow::

        proxy → ClassifierAgent  →  proxy → RAGAgent  →  proxy → EvaluatorAgent
        → EscalationDetector → TicketRouter → persist Resolution

    Each two-agent exchange uses ``max_turns=1``.  Results are threaded from
    stage to stage as structured JSON dicts.

    Args:
        classifier_agent: :class:`~src.agents.classifier_agent.ClassifierAgent`.
        rag_agent: :class:`~src.agents.rag_agent.RAGAgent`.
        evaluator_agent: :class:`~src.agents.evaluator_agent.EvaluatorAgent`.
        proxy: :class:`~src.agents.user_proxy.TicketUserProxy`.
        router: :class:`~src.routing.router.TicketRouter`.
        escalation_detector: :class:`~src.routing.escalation.EscalationDetector`.
        ticket_repo: For loading tickets and updating their status.
        resolution_repo: For persisting the final Resolution row.
    """

    def __init__(
        self,
        classifier_agent: "ClassifierAgent",
        rag_agent: "RAGAgent",
        evaluator_agent: "EvaluatorAgent",
        proxy: "TicketUserProxy",
        router: "TicketRouter",
        escalation_detector: "EscalationDetector",
        ticket_repo: "TicketRepository",
        resolution_repo: "ResolutionRepository",
    ) -> None:
        self._classifier_agent = classifier_agent
        self._rag_agent = rag_agent
        self._evaluator_agent = evaluator_agent
        self._proxy = proxy
        self._router = router
        self._escalation_detector = escalation_detector
        self._ticket_repo = ticket_repo
        self._resolution_repo = resolution_repo

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process_ticket(self, ticket_id: uuid.UUID) -> Resolution:
        """Run the full pipeline and return the persisted Resolution.

        Args:
            ticket_id: UUID of the ticket to process (must already be in DB).

        Returns:
            The persisted :class:`~src.db.models.Resolution` row.

        Raises:
            TicketNotFoundError: If the ticket does not exist in the DB.
        """
        ticket = await self._ticket_repo.get_by_id(ticket_id)
        if ticket is None:
            raise TicketNotFoundError(str(ticket_id))

        # ── Stage 1: Classification ────────────────────────────────────────────
        await self._ticket_repo.update_status(ticket_id, TicketStatus.CLASSIFYING)

        classification_raw = await self._classifier_agent._classify({
            "type": "CLASSIFY",
            "ticket_id": str(ticket_id),
            "title": ticket.title,
            "description": ticket.description,
        })

        if classification_raw.get("type") == "ERROR":
            return await self._escalate(
                ticket_id=ticket_id,
                reason="Classification pipeline failed",
                resolution_text=None,
                retrieved_entries=None,
                quality_score=None,
                category=None,
            )

        # ── Stage 2: RAG (retrieve + generate) ────────────────────────────────
        rag_raw = await self._rag_agent._run_rag({
            "type": "RETRIEVE_AND_GENERATE",
            "ticket_id": str(ticket_id),
            "title": ticket.title,
            "description": ticket.description,
            "classification": classification_raw,
        })

        if rag_raw.get("type") == "ERROR":
            return await self._escalate(
                ticket_id=ticket_id,
                reason="RAG pipeline failed",
                resolution_text=None,
                retrieved_entries=None,
                quality_score=None,
                category=TicketCategory(classification_raw["predicted_category"]),
            )

        # ── Stage 3: Evaluation ────────────────────────────────────────────────
        eval_raw = await self._evaluator_agent._evaluate({
            "type": "EVALUATE",
            "ticket_id": str(ticket_id),
            "title": ticket.title,
            "description": ticket.description,
            "resolution_text": rag_raw["resolution_text"],
        })

        quality_score: float = eval_raw.get("quality_score", 0.0)
        category = TicketCategory(classification_raw["predicted_category"])

        # ── Stage 4: Routing ───────────────────────────────────────────────────
        classification_output = self._build_classification_output(classification_raw)
        routing: RoutingResult = self._router.decide(classification_output, quality_score)

        # ── Stage 5: Escalation detection ─────────────────────────────────────
        escalation_ctx = await self._escalation_detector.check(
            category=category,
            exclude_ticket_id=ticket_id,
        )

        # ── Stage 6: Persist Resolution ────────────────────────────────────────
        final_status = TicketStatus[routing.decision.name]

        resolution = Resolution(
            ticket_id=ticket_id,
            suggested_steps=rag_raw.get("resolution_text"),
            retrieved_tickets=rag_raw.get("retrieved_entries"),
            llm_quality_score=quality_score,
            routing_decision=routing.decision,
            assigned_department=routing.assigned_department,
            escalation_reason=routing.escalation_reason,
            is_repeated_issue=escalation_ctx.is_repeated_issue,
        )
        resolution = await self._resolution_repo.create(resolution)
        await self._ticket_repo.update_status(ticket_id, final_status)

        logger.info(
            "Ticket processing complete",
            extra={
                "metadata": {
                    "ticket_id": str(ticket_id),
                    "routing_decision": routing.decision.value,
                    "department": routing.assigned_department,
                    "quality_score": quality_score,
                    "is_repeated_issue": escalation_ctx.is_repeated_issue,
                }
            },
        )
        return resolution

    # ── Private helpers ────────────────────────────────────────────────────────

    def _extract_last_reply(self, agent: object) -> dict:
        """Extract and parse the last reply dict from an agent.

        Returns an ERROR dict if the reply cannot be parsed.
        """
        try:
            last = self._proxy.last_message(agent)  # type: ignore[arg-type]
            content = last.get("content", "")
            return json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            logger.warning(
                "Failed to extract agent reply",
                extra={"metadata": {"error": str(exc)}},
            )
            return {"type": "ERROR", "message": str(exc)}

    async def _escalate(
        self,
        ticket_id: uuid.UUID,
        reason: str,
        resolution_text: str | None,
        retrieved_entries: list | None,
        quality_score: float | None,
        category: TicketCategory | None,
    ) -> Resolution:
        """Create an ESCALATED Resolution and update ticket status."""
        resolution = Resolution(
            ticket_id=ticket_id,
            suggested_steps=resolution_text,
            retrieved_tickets=retrieved_entries,
            llm_quality_score=quality_score,
            routing_decision=RoutingDecision.ESCALATED,
            assigned_department=None,
            escalation_reason=reason,
            is_repeated_issue=False,
        )
        resolution = await self._resolution_repo.create(resolution)
        await self._ticket_repo.update_status(ticket_id, TicketStatus.ESCALATED)
        logger.warning(
            "Ticket escalated due to pipeline failure",
            extra={"metadata": {"ticket_id": str(ticket_id), "reason": reason}},
        )
        return resolution

    @staticmethod
    def _build_classification_output(raw: dict) -> ClassificationOutput:
        """Reconstruct a ClassificationOutput from the agent message dict."""
        return ClassificationOutput(
            predicted_category=TicketCategory(raw["predicted_category"]),
            confidence=raw["confidence"],
            confidence_level=ConfidenceLevel(raw["confidence_level"]),
            top_categories=raw.get("top_categories", []),
            is_multi_domain=raw.get("is_multi_domain", False),
            classification_method=raw.get("classification_method", "unknown"),
        )
