"""Queries for `ticket_embeddings` — the 384-dim vector per ticket."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.db.models import TicketEmbedding
from src.db.repositories.base_repo import BaseRepository


class EmbeddingRepository(BaseRepository[TicketEmbedding]):
    model = TicketEmbedding

    async def get_by_ticket_id(self, ticket_id: uuid.UUID) -> TicketEmbedding | None:
        stmt = select(TicketEmbedding).where(TicketEmbedding.ticket_id == ticket_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_near_duplicate(
        self, query_vector: list[float], similarity_threshold: float
    ) -> uuid.UUID | None:
        """Closest existing ticket by cosine similarity, if it clears
        `similarity_threshold` (e.g. 0.95). Used by the ingestion
        `Deduplicator` for near-duplicate detection — distinct from the exact
        SHA-256 content-hash match, which catches identical text only.

        pgvector's `cosine_distance` is `1 - cosine_similarity`, so the
        threshold is applied as a max-distance cutoff.
        """
        max_distance = 1.0 - similarity_threshold
        distance = TicketEmbedding.embedding.cosine_distance(query_vector)
        stmt = (
            select(TicketEmbedding.ticket_id, distance.label("distance"))
            .order_by(distance)
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None or row.distance > max_distance:
            return None
        return row.ticket_id
