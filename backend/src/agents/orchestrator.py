"""TicketOrchestrator — gated pipeline with pre-generation review and resume path.

Stage sequence (docs/03_BACKEND_DESIGN.md §100):
  1. Classify   → ClassifierAgent._classify
  2. Gate check → TicketRouter.pre_generation_check
     - LOW confidence or multi-domain → AWAITING_REVIEW, pipeline halts
  3. Retrieve   → RAGAgent._run_rag
  4. Generate   → (inside RAGAgent)
  5. Evaluate   → EvaluatorAgent._evaluate
  6. Route      → TicketRouter.decide
  7. Escalate?  → EscalationDetector.should_escalate
  8. Persist    → Classification + Resolution rows, Ticket status

`resume_after_reclassification` re-enters at Stage 3 with a human-supplied
category, bypassing classification (confidence = 1.0 synthetic, method =
HUMAN_REVIEWER — docs/03_BACKEND_DESIGN.md §120).

Responsibilities are kept narrow (audit fix L3): status transitions delegate
to ticket_repo; persistence helpers are extracted to `_persist_classification`
and `_persist_resolution`; factory helpers are `_build_classifier`,
`_build_rag`, `_build_evaluator` (audit fix L4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from src.agents.classifier_agent import ClassifierAgent
from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.rag_agent import RAGAgent
from src.classification.classifier import ClassificationOutput, build_classifier
from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models import (
    ClassificationMethod,
    ConfidenceLevel,
    ResolutionStep,
    RoutingDecision,
    Ticket,
    TicketCategory,
    TicketStatus,
)
from src.db.repositories.classification_repo import ClassificationRepository
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.embedding.generator import EmbeddingGenerator
from src.rag.generator import GeneratorProtocol, build_generator
from src.rag.knowledge_base import KnowledgeBaseIndex
from src.rag.reranker import MMRReranker
from src.rag.retriever import HybridRetriever
from src.monitoring.metrics import record_awaiting_review, record_pipeline_complete
from src.routing.escalation import EscalationDetector
from src.routing.router import RoutingResult, TicketRouter

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OrchestratorResult:
    ticket_id: uuid.UUID
    routing_decision: RoutingDecision
    routing_reason: str
    steps: list[ResolutionStep] | None
    llm_quality_score: float | None
    escalated: bool
    escalation_reason: str | None


class TicketOrchestrator:
    def __init__(
        self,
        classifier_agent: ClassifierAgent,
        rag_agent: RAGAgent,
        evaluator_agent: EvaluatorAgent,
        router: TicketRouter,
        escalation_detector: EscalationDetector,
        ticket_repo: TicketRepository,
        classification_repo: ClassificationRepository,
        resolution_repo: ResolutionRepository,
    ) -> None:
        self._classifier_agent = classifier_agent
        self._rag_agent = rag_agent
        self._evaluator_agent = evaluator_agent
        self._router = router
        self._escalation_detector = escalation_detector
        self._ticket_repo = ticket_repo
        self._classification_repo = classification_repo
        self._resolution_repo = resolution_repo

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def run(self, ticket: Ticket) -> OrchestratorResult:
        """First-pass pipeline for a NEW ticket."""
        ticket_id = ticket.id

        # Stage 1: Classify
        await self._ticket_repo.update_status(ticket_id, TicketStatus.CLASSIFYING)
        classification = await self._classifier_agent._classify(  # noqa: SLF001
            ticket.title, ticket.description
        )
        await self._persist_classification(ticket_id, classification, ClassificationMethod.MODEL)

        # Stage 2: Pre-generation gate
        pre_check = self._router.pre_generation_check(classification)
        if pre_check is not None:
            return await self._await_review(ticket_id, pre_check, classification.confidence)

        await self._ticket_repo.update_status(ticket_id, TicketStatus.CLASSIFIED)
        return await self._run_from_classification(ticket, classification)

    async def resume_after_reclassification(
        self, ticket: Ticket, human_category: TicketCategory
    ) -> OrchestratorResult:
        """Resume a pipeline halted at AWAITING_REVIEW with a human-supplied category."""
        ticket_id = ticket.id

        # Synthetic classification — confidence=1.0, method=HUMAN_REVIEWER
        synthetic = ClassificationOutput(
            category=human_category,
            confidence=1.0,
            confidence_level="high",
            is_multi_domain=False,
            top2_gap=1.0,
            classification_method="human_reviewer",
            all_probabilities={human_category.value: 1.0},
        )

        await self._classification_repo.delete_by_ticket_id(ticket_id)
        await self._resolution_repo.delete_by_ticket_id(ticket_id)
        await self._persist_classification(
            ticket_id, synthetic, ClassificationMethod.HUMAN_REVIEWER
        )
        await self._ticket_repo.update_category(ticket_id, human_category)
        await self._ticket_repo.update_status(ticket_id, TicketStatus.CLASSIFIED)

        return await self._run_from_classification(ticket, synthetic)

    # ------------------------------------------------------------------
    # Shared pipeline body (Stages 3-8)
    # ------------------------------------------------------------------

    async def _run_from_classification(
        self,
        ticket: Ticket,
        classification: ClassificationOutput,
    ) -> OrchestratorResult:
        ticket_id = ticket.id

        # Stage 3-4: Retrieve + Generate
        await self._ticket_repo.update_status(ticket_id, TicketStatus.RETRIEVING)
        steps, context = await self._rag_agent._run_rag(  # noqa: SLF001
            ticket.title, ticket.description, classification.category
        )

        # Stage 5: Evaluate
        await self._ticket_repo.update_status(ticket_id, TicketStatus.EVALUATING)
        quality_score = await self._evaluator_agent._evaluate(  # noqa: SLF001
            ticket.title, ticket.description, classification.category, steps, context
        )

        # Stage 6: Route
        routing: RoutingResult = self._router.decide(classification, quality_score)

        # Stage 7: Escalation override
        escalation_reasons: list[str] = []
        if routing.decision != RoutingDecision.AWAITING_REVIEW:
            if self._escalation_detector.should_escalate(ticket, escalation_reasons):
                routing = RoutingResult(
                    decision=RoutingDecision.ESCALATED,
                    reason="; ".join(escalation_reasons),
                )

        escalated = routing.decision == RoutingDecision.ESCALATED
        escalation_reason = "; ".join(escalation_reasons) if escalation_reasons else None

        # Stage 8: Persist resolution + final status
        retrieved_dicts = [
            {"title": e.title, "category": e.category.value if e.category else None}
            for e in context
        ]
        await self._resolution_repo.create(
            ticket_id=ticket_id,
            suggested_steps=[s.model_dump() for s in steps],
            retrieved_tickets=retrieved_dicts,
            llm_quality_score=quality_score,
            routing_decision=routing.decision,
            escalation_reason=escalation_reason,
        )

        terminal_map = {
            RoutingDecision.AUTO_RESOLVED: TicketStatus.AUTO_RESOLVED,
            RoutingDecision.ASSIGNED: TicketStatus.ASSIGNED,
            RoutingDecision.ESCALATED: TicketStatus.ESCALATED,
        }
        final_status = terminal_map.get(routing.decision, TicketStatus.ASSIGNED)
        await self._ticket_repo.update_status(ticket_id, final_status)
        await self._ticket_repo.update_category(ticket_id, classification.category)

        record_pipeline_complete(
            routing_decision=routing.decision.value,
            category=classification.category.value,
            confidence=classification.confidence,
            quality_score=quality_score,
        )

        logger.info(
            "orchestrator_complete",
            ticket_id=str(ticket_id),
            decision=routing.decision.value,
            quality_score=round(quality_score, 3),
            escalated=escalated,
        )

        return OrchestratorResult(
            ticket_id=ticket_id,
            routing_decision=routing.decision,
            routing_reason=routing.reason,
            steps=steps,
            llm_quality_score=quality_score,
            escalated=escalated,
            escalation_reason=escalation_reason,
        )

    async def _await_review(
        self, ticket_id: uuid.UUID, pre_check: RoutingResult, confidence: float = 0.0
    ) -> OrchestratorResult:
        await self._resolution_repo.create(
            ticket_id=ticket_id,
            suggested_steps=None,
            retrieved_tickets=None,
            llm_quality_score=None,
            routing_decision=RoutingDecision.AWAITING_REVIEW,
            escalation_reason=None,
        )
        await self._ticket_repo.update_status(ticket_id, TicketStatus.AWAITING_REVIEW)
        record_awaiting_review(confidence=confidence)

        logger.info(
            "orchestrator_awaiting_review",
            ticket_id=str(ticket_id),
            reason=pre_check.reason,
        )
        return OrchestratorResult(
            ticket_id=ticket_id,
            routing_decision=RoutingDecision.AWAITING_REVIEW,
            routing_reason=pre_check.reason,
            steps=None,
            llm_quality_score=None,
            escalated=False,
            escalation_reason=None,
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist_classification(
        self,
        ticket_id: uuid.UUID,
        classification: ClassificationOutput,
        method: ClassificationMethod,
    ) -> None:
        top_categories = [
            {"category": cat, "probability": prob}
            for cat, prob in sorted(
                classification.all_probabilities.items(), key=lambda kv: kv[1], reverse=True
            )
        ]
        await self._classification_repo.create(
            ticket_id=ticket_id,
            predicted_category=classification.category,
            confidence=classification.confidence,
            confidence_level=ConfidenceLevel(classification.confidence_level),
            top_categories=top_categories,
            is_multi_domain=classification.is_multi_domain,
            classification_method=method,
        )


# ------------------------------------------------------------------
# Factory helpers (audit fix L4 — no monolithic _build_orchestrator)
# ------------------------------------------------------------------


def _build_classifier(settings: object) -> ClassifierAgent:
    from src.core.config import Settings

    assert isinstance(settings, Settings)
    model_path = Path(settings.model_dir) / "classifier.pkl"
    classifier = build_classifier(model_path)
    return ClassifierAgent(classifier)


def _build_rag(
    settings: object,
    generator: EmbeddingGenerator,
    bm25_index: KnowledgeBaseIndex,
    kb_repo: object,
    llm: GeneratorProtocol,
) -> RAGAgent:
    from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository

    assert isinstance(kb_repo, KnowledgeBaseRepository)
    retriever = HybridRetriever(kb_repo, generator, bm25_index)
    reranker = MMRReranker(generator)
    return RAGAgent(retriever, reranker, llm)


def _build_evaluator(llm: GeneratorProtocol) -> EvaluatorAgent:
    return EvaluatorAgent(llm)


def build_orchestrator(
    ticket_repo: TicketRepository,
    classification_repo: ClassificationRepository,
    resolution_repo: ResolutionRepository,
    kb_repo: object,
    bm25_index: KnowledgeBaseIndex,
) -> TicketOrchestrator:
    """Wire and return a fully-configured TicketOrchestrator."""
    settings = get_settings()
    generator = EmbeddingGenerator(
        model_name=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
    )
    llm = build_generator()

    return TicketOrchestrator(
        classifier_agent=_build_classifier(settings),
        rag_agent=_build_rag(settings, generator, bm25_index, kb_repo, llm),
        evaluator_agent=_build_evaluator(llm),
        router=TicketRouter(),
        escalation_detector=EscalationDetector(),
        ticket_repo=ticket_repo,
        classification_repo=classification_repo,
        resolution_repo=resolution_repo,
    )
