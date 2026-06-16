"""Ticket routes: ingest, get, list, reclassify."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from src.api.envelope import collection, ok
from src.api.middleware.auth import CurrentUser
from src.api.middleware.rate_limiter import rate_limit
from src.db.database import session_scope
from src.db.models import TicketCategory, TicketStatus
from src.db.repositories.ticket_repo import TicketRepository, TicketSearchFilters
from src.schemas.ticket import TicketIngestRequest

router = APIRouter(
    prefix="/tickets",
    tags=["tickets"],
    dependencies=[Depends(rate_limit)],
)


def _ticket_dict(ticket: object) -> dict:
    from src.db.models import Ticket

    t: Ticket = ticket  # type: ignore[assignment]
    d: dict = {
        "id": str(t.id),
        "title": t.title,
        "description": t.description,
        "category": t.category.value if t.category else None,
        "priority": t.priority,
        "status": t.status.value,
        "source": t.source.value,
        "pii_detected": t.pii_detected,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
        "classification": None,
        "resolution": None,
    }
    if t.classification is not None:
        c = t.classification
        d["classification"] = {
            "predicted_category": c.predicted_category.value,
            "confidence": c.confidence,
            "confidence_level": c.confidence_level.value,
            "is_multi_domain": c.is_multi_domain,
            "top_categories": c.top_categories,
            "classification_method": c.classification_method.value,
        }
    if t.resolution is not None:
        r = t.resolution
        d["resolution"] = {
            "routing_decision": r.routing_decision.value,
            "suggested_steps": r.suggested_steps,
            "retrieved_tickets": r.retrieved_tickets,
            "llm_quality_score": r.llm_quality_score,
            "escalation_reason": r.escalation_reason,
            "assigned_department": r.assigned_department,
        }
    return d


async def _run_pipeline_background(ticket_id: uuid.UUID) -> None:
    """Background task: build orchestrator and run the full pipeline."""
    from src.agents.orchestrator import build_orchestrator
    from src.db.repositories.classification_repo import ClassificationRepository
    from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
    from src.db.repositories.resolution_repo import ResolutionRepository
    from src.rag.knowledge_base import build_index

    async with session_scope() as session:
        ticket_repo = TicketRepository(session)
        classification_repo = ClassificationRepository(session)
        resolution_repo = ResolutionRepository(session)
        kb_repo = KnowledgeBaseRepository(session)

        ticket = await ticket_repo.get_with_relations(ticket_id)
        if ticket is None:
            return

        all_kb = await kb_repo.get_all_for_bm25()
        bm25_index = await build_index(all_kb)

        orch = build_orchestrator(
            ticket_repo=ticket_repo,
            classification_repo=classification_repo,
            resolution_repo=resolution_repo,
            kb_repo=kb_repo,
            bm25_index=bm25_index,
        )
        await orch.run(ticket)
        await session.commit()


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_ticket(
    request: TicketIngestRequest,
    background_tasks: BackgroundTasks,
    _: CurrentUser,
) -> dict:
    async with session_scope() as session:
        from src.db.repositories.embedding_repo import EmbeddingRepository
        from src.ingestion.pipeline import build_ingestion_pipeline

        ticket_repo = TicketRepository(session)
        embedding_repo = EmbeddingRepository(session)
        pipeline = build_ingestion_pipeline(
            ticket_repo=ticket_repo,
            embedding_repo=embedding_repo,
            similarity_threshold=0.95,
        )
        result = await pipeline.run(request)
        await session.commit()

    background_tasks.add_task(_run_pipeline_background, result.ticket.id)

    return ok(
        {
            "ticket_id": str(result.ticket.id),
            "status": result.ticket.status.value,
            "message": "Ticket queued for processing.",
        }
    )


@router.get("/{ticket_id}")
async def get_ticket(ticket_id: uuid.UUID, _: CurrentUser) -> dict:
    async with session_scope() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_with_relations(ticket_id)

    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    return ok(_ticket_dict(ticket))


@router.get("/")
async def list_tickets(
    _: CurrentUser,
    category: TicketCategory | None = None,
    ticket_status: TicketStatus | None = Query(None, alias="status"),
    priority: int | None = None,
    offset: int = 0,
    limit: int = Query(default=50, le=200),
) -> dict:
    filters = TicketSearchFilters(
        category=category,
        status=ticket_status,
        priority=priority,
        offset=offset,
        limit=limit,
    )
    async with session_scope() as session:
        repo = TicketRepository(session)
        tickets, total = await repo.search(filters)

    return collection(
        [_ticket_dict(t) for t in tickets],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/{ticket_id}/reclassify", status_code=status.HTTP_202_ACCEPTED)
async def reclassify_ticket(
    ticket_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    body: dict,
    _: CurrentUser,
) -> dict:
    category_raw = body.get("category", "")
    try:
        category = TicketCategory(category_raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid category: '{category_raw}'.")

    async with session_scope() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_with_relations(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="Ticket not found.")
        if ticket.status != TicketStatus.AWAITING_REVIEW:
            raise HTTPException(
                status_code=409,
                detail=f"Ticket is not awaiting review (status={ticket.status.value}).",
            )
        await repo.update_status(ticket_id, TicketStatus.CLASSIFYING)
        await session.commit()

    async def _resume(tid: uuid.UUID, cat: TicketCategory) -> None:
        from src.agents.orchestrator import build_orchestrator
        from src.db.repositories.classification_repo import ClassificationRepository
        from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
        from src.db.repositories.resolution_repo import ResolutionRepository
        from src.rag.knowledge_base import build_index

        async with session_scope() as s:
            t_repo = TicketRepository(s)
            c_repo = ClassificationRepository(s)
            r_repo = ResolutionRepository(s)
            kb_repo = KnowledgeBaseRepository(s)

            t = await t_repo.get_with_relations(tid)
            if t is None:
                return
            all_kb = await kb_repo.get_all_for_bm25()
            bm25_index = await build_index(all_kb)
            orch = build_orchestrator(
                ticket_repo=t_repo,
                classification_repo=c_repo,
                resolution_repo=r_repo,
                kb_repo=kb_repo,
                bm25_index=bm25_index,
            )
            await orch.resume_after_reclassification(t, cat)
            await s.commit()

    background_tasks.add_task(_resume, ticket_id, category)

    return ok({"ticket_id": str(ticket_id), "status": TicketStatus.CLASSIFYING.value})
