"""Knowledge base search endpoint — semantic (dense) retrieval via pgvector."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.middleware.auth import CurrentUser
from src.api.middleware.rate_limiter import rate_limit
from src.api.envelope import collection
from src.db.database import session_scope
from src.db.models import KnowledgeBaseEntry, TicketCategory
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.embedding.generator import EmbeddingGenerator

router = APIRouter(
    prefix="/kb",
    tags=["knowledge-base"],
    dependencies=[Depends(rate_limit)],
)

_generator = EmbeddingGenerator()


def _entry_dict(e: KnowledgeBaseEntry, score: float | None = None) -> dict:
    d: dict = {
        "id": str(e.id),
        "title": e.title,
        "content": e.resolution,
        "category": e.category.value,
        "source_ticket_id": e.source,
        "created_at": e.created_at.isoformat(),
    }
    if score is not None:
        d["relevance_score"] = round(score, 4)
    return d


@router.get("/")
async def search_kb(
    _: CurrentUser,
    q: str | None = Query(default=None, max_length=200),
    category: TicketCategory | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    async with session_scope() as session:
        repo = KnowledgeBaseRepository(session)

        if q and q.strip():
            # Semantic search: embed query → cosine ANN via pgvector
            query_vector = await _generator.encode_one(q.strip())
            raw = await repo.search_similar(
                query_vector=query_vector,
                top_k=limit,
                category_filter=category,
            )
            # Convert distance to similarity score (1 - cosine_distance)
            entries = [_entry_dict(e, score=round(1.0 - dist, 4)) for e, dist in raw]
        else:
            # No query — fall back to recency browse with optional category filter
            rows, total = await repo.search(
                query=None,
                category=category,
                offset=0,
                limit=limit,
            )
            entries = [_entry_dict(e) for e in rows]

        return collection(entries, total=len(entries), offset=0, limit=limit)
