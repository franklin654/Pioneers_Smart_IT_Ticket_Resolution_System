"""Shared FastAPI dependency functions.

Provides injectable dependencies for:
    - Database session (delegates to ``src.db.database.get_db``)
    - Repository instances (TicketRepository, ResolutionRepository)
    - IngestionPipeline (wraps ``build_ingestion_pipeline``)
    - Background orchestrator runner (``run_orchestrator_background``)

The orchestrator background runner creates its own ``AsyncSession`` so it is
fully independent of the request session, which may be closed by the time the
background task executes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.logging import get_logger
from src.db.database import AsyncSessionLocal, get_db
from src.db.repositories.classification_repo import ClassificationRepository
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.ingestion.pipeline import IngestionPipeline, build_ingestion_pipeline

logger = get_logger(__name__)

# ── Re-export get_db so routes can import it from one place ──────────────────
__all__ = [
    "get_db",
    "get_ticket_repo",
    "get_resolution_repo",
    "get_ingestion_pipeline",
    "run_orchestrator_background",
]


# ── Repository dependencies ───────────────────────────────────────────────────


async def get_ticket_repo(
    db: AsyncSession = Depends(get_db),
) -> TicketRepository:
    """Inject a :class:`~src.db.repositories.ticket_repo.TicketRepository`."""
    return TicketRepository(db)


async def get_resolution_repo(
    db: AsyncSession = Depends(get_db),
) -> ResolutionRepository:
    """Inject a :class:`~src.db.repositories.resolution_repo.ResolutionRepository`."""
    return ResolutionRepository(db)


# ── Ingestion pipeline dependency ─────────────────────────────────────────────


async def get_ingestion_pipeline(
    db: AsyncSession = Depends(get_db),
) -> IngestionPipeline:
    """Inject a fully-wired :class:`~src.ingestion.pipeline.IngestionPipeline`.

    Embedding-based near-duplicate detection is disabled here; it requires
    the full EmbeddingGenerator which is a heavy model load.  Exact-hash
    deduplication still runs on every request.
    """
    return build_ingestion_pipeline(session=db, embedding_generator=None)


# ── Background orchestrator runner ────────────────────────────────────────────


async def run_orchestrator_background(ticket_id: uuid.UUID) -> None:
    """Run the full agent pipeline for *ticket_id* in a background task.

    Creates its own ``AsyncSession`` (independent of the closed request
    session) and builds all agent/service objects from scratch.  Any
    exception is caught and logged so the background task never crashes
    the worker.

    Args:
        ticket_id: UUID of an already-persisted ticket with status NEW.
    """
    try:
        async with AsyncSessionLocal() as session:
            orchestrator = _build_orchestrator(session, get_settings())
            await orchestrator.process_ticket(ticket_id)
            await session.commit()  # flush→commit: status updates and resolution are not auto-committed
        await _record_processing_metrics(ticket_id)
    except Exception as exc:
        logger.error(
            "Background orchestrator failed",
            extra={"metadata": {"ticket_id": str(ticket_id), "error": str(exc)}},
        )


# ── Post-processing metrics ───────────────────────────────────────────────────


async def _record_processing_metrics(ticket_id: uuid.UUID) -> None:
    """Record ML and business metrics for a fully-processed ticket.

    Uses a fresh session — called after the orchestrator session has closed.
    Silently skips if the ticket or its relations are not yet available.
    """
    try:
        from src.monitoring.metrics import (
            AUTO_RESOLVE_RATE,
            CLASSIFICATION_CONFIDENCE,
            LLM_QUALITY_SCORE,
            TICKET_PROCESSING_DURATION,
        )

        async with AsyncSessionLocal() as session:
            ticket = await TicketRepository(session).get_with_relations(ticket_id)

        if not (ticket and ticket.classification and ticket.resolution):
            return

        cls = ticket.classification
        res = ticket.resolution
        routing = res.routing_decision.value

        if ticket.created_at and ticket.updated_at:
            elapsed = (ticket.updated_at - ticket.created_at).total_seconds()
            if elapsed > 0:
                TICKET_PROCESSING_DURATION.labels(routing_decision=routing).observe(elapsed)

        CLASSIFICATION_CONFIDENCE.labels(
            category=cls.predicted_category.value,
            confidence_level=cls.confidence_level.value,
        ).observe(cls.confidence)

        if res.llm_quality_score is not None:
            LLM_QUALITY_SCORE.labels(routing_decision=routing).observe(res.llm_quality_score)

        AUTO_RESOLVE_RATE.set(1.0 if routing == "auto_resolved" else 0.0)

    except Exception as exc:
        logger.warning(
            "Failed to record processing metrics",
            extra={"metadata": {"ticket_id": str(ticket_id), "error": str(exc)}},
        )


# ── Orchestrator factory ──────────────────────────────────────────────────────


def _build_orchestrator(session: AsyncSession, settings: Settings):
    """Construct a fully-wired :class:`~src.agents.orchestrator.TicketOrchestrator`.

    Imports are deferred to this function so the heavy ML models (classifier,
    embeddings) are loaded only when a ticket actually needs processing, not
    at import time.

    Args:
        session: Active async DB session (owned by the background task).
        settings: Application settings.

    Returns:
        A ready-to-use :class:`~src.agents.orchestrator.TicketOrchestrator`.
    """
    from src.agents.classifier_agent import ClassifierAgent
    from src.agents.evaluator_agent import EvaluatorAgent
    from src.agents.orchestrator import TicketOrchestrator
    from src.agents.rag_agent import RAGAgent
    from src.agents.user_proxy import TicketUserProxy
    from src.classification.classifier import TicketClassifier
    from src.db.repositories.classification_repo import ClassificationRepository
    from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
    from src.db.repositories.resolution_repo import ResolutionRepository
    from src.db.repositories.ticket_repo import TicketRepository
    from src.embedding.generator import EmbeddingGenerator
    from src.rag.generator import LLMGeneratorFactory, RAGGenerator
    from src.rag.knowledge_base import KnowledgeBase
    from src.rag.reranker import MMRReranker
    from src.rag.retriever import HybridRetriever
    from src.routing.escalation import EscalationDetector
    from src.routing.router import TicketRouter

    # Repositories
    ticket_repo = TicketRepository(session)
    resolution_repo = ResolutionRepository(session)
    classification_repo = ClassificationRepository(session)
    kb_repo = KnowledgeBaseRepository(session)

    # Embedding + classifier — share the embedding generator to avoid double load
    embedding_gen = EmbeddingGenerator(settings)
    classifier = TicketClassifier.from_settings(settings, embedding_generator=embedding_gen)

    # RAG components
    kb = KnowledgeBase(repo=kb_repo, embedding_generator=embedding_gen, settings=settings)
    retriever = HybridRetriever(kb=kb, kb_repo=kb_repo, settings=settings)
    reranker = MMRReranker(settings=settings)
    llm_gen = LLMGeneratorFactory.from_settings(settings)
    rag_generator = RAGGenerator(llm=llm_gen, settings=settings)

    # Agents
    classifier_agent = ClassifierAgent(
        classifier=classifier,
        ticket_repo=ticket_repo,
        classification_repo=classification_repo,
        settings=settings,
    )
    rag_agent = RAGAgent(
        kb=kb,
        kb_repo=kb_repo,
        retriever=retriever,
        reranker=reranker,
        rag_generator=rag_generator,
        embedding_generator=embedding_gen,
        ticket_repo=ticket_repo,
        settings=settings,
    )
    evaluator_agent = EvaluatorAgent(
        llm_generator=llm_gen,
        ticket_repo=ticket_repo,
        settings=settings,
    )

    router = TicketRouter()
    proxy = TicketUserProxy(router=router)
    escalation_detector = EscalationDetector(ticket_repo=ticket_repo)

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
