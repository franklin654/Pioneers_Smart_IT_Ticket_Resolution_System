"""Queries for `knowledge_base_entries` — dense (pgvector) retrieval and the
bounded full-table scan the BM25 index is built from.

No raw SQL string interpolation anywhere (audit fix M3) — every query is
built with the ORM's `select().where()`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.db.models import KnowledgeBaseEntry, TicketCategory
from src.db.repositories.base_repo import BaseRepository

_DEFAULT_BM25_LOAD_LIMIT = 50_000


class KnowledgeBaseRepository(BaseRepository[KnowledgeBaseEntry]):
    model = KnowledgeBaseEntry

    async def search_similar(
        self,
        query_vector: list[float],
        top_k: int = 20,
        category_filter: TicketCategory | None = None,
    ) -> list[tuple[KnowledgeBaseEntry, float]]:
        """Cosine-distance ANN search via pgvector. Returns (entry, distance) —
        smaller distance is more similar."""
        distance = KnowledgeBaseEntry.embedding.cosine_distance(query_vector)
        stmt = select(KnowledgeBaseEntry, distance.label("distance")).where(
            KnowledgeBaseEntry.embedding.is_not(None)
        )
        if category_filter is not None:
            stmt = stmt.where(KnowledgeBaseEntry.category == category_filter)
        stmt = stmt.order_by(distance).limit(top_k)

        rows = (await self.session.execute(stmt)).all()
        return [(entry, dist) for entry, dist in rows]

    async def get_all_for_bm25(
        self, limit: int = _DEFAULT_BM25_LOAD_LIMIT
    ) -> list[KnowledgeBaseEntry]:
        """Bounded load for building the in-memory BM25 index — audit fix M4
        (v1's equivalent had no LIMIT and risked OOM at scale)."""
        stmt = select(KnowledgeBaseEntry).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)

    async def get_by_category(
        self, category: TicketCategory, limit: int = 1000
    ) -> list[KnowledgeBaseEntry]:
        stmt = (
            select(KnowledgeBaseEntry).where(KnowledgeBaseEntry.category == category).limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)

    async def set_embedding(self, entry_id: uuid.UUID, embedding: list[float]) -> None:
        entry = await self.get_by_id(entry_id)
        if entry is None:
            return
        entry.embedding = embedding
        await self.session.flush()
