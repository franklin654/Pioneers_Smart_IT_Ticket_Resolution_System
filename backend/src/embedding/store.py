"""Embedding persistence and nearest-neighbour lookup via pgvector.

Coordinates between the EmbeddingGenerator and EmbeddingRepository so
callers don't need to touch both directly.
"""

from __future__ import annotations

from uuid import UUID

from src.core.logging import get_logger
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.embedding.generator import EmbeddingGenerator

logger = get_logger(__name__)


class EmbeddingStore:
    def __init__(self, generator: EmbeddingGenerator, repo: EmbeddingRepository) -> None:
        self._generator = generator
        self._repo = repo

    async def upsert_ticket_embedding(self, ticket_id: UUID, text: str) -> None:
        """Generate and persist (or replace) the embedding for one ticket."""
        vector = await self._generator.encode_one(text)
        existing = await self._repo.get_by_ticket_id(ticket_id)
        if existing is not None:
            await self._repo.delete(existing)
        await self._repo.create(ticket_id=ticket_id, embedding=vector)
        logger.debug("ticket_embedding_upserted", ticket_id=str(ticket_id))

    async def find_near_duplicate(self, text: str, similarity_threshold: float) -> UUID | None:
        """Return the ticket_id of the nearest stored ticket if similarity ≥ threshold."""
        vector = await self._generator.encode_one(text)
        return await self._repo.find_near_duplicate(vector, similarity_threshold)
