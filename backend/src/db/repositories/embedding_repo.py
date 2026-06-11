"""Repository for TicketEmbedding with pgvector ANN similarity search."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text

from src.db.models import TicketEmbedding
from src.db.repositories.base_repo import BaseRepository


@dataclass
class SimilarTicketResult:
    """Result item from an ANN similarity search against ticket embeddings."""

    ticket_id: uuid.UUID
    embedding_id: uuid.UUID
    similarity_score: float  # cosine similarity in range [0, 1]


class EmbeddingRepository(BaseRepository[TicketEmbedding]):
    """Repository for :class:`~src.db.models.TicketEmbedding`.

    Exposes ``upsert`` (create-or-replace) and ``find_similar`` (pgvector
    cosine ANN search) in addition to the standard CRUD from
    :class:`BaseRepository`.
    """

    model_class = TicketEmbedding

    async def upsert(
        self,
        ticket_id: uuid.UUID,
        vector: list[float],
        model_version: str,
    ) -> TicketEmbedding:
        """Create or replace the embedding for a ticket.

        If an embedding already exists for ``ticket_id``, it is updated
        in-place so the unique constraint on ``ticket_id`` is never violated.

        Args:
            ticket_id: UUID of the parent ticket.
            vector: 384-dimensional float list.
            model_version: Identifier for the embedding model used (e.g.
                ``"all-MiniLM-L6-v2"``).

        Returns:
            The persisted (or updated) :class:`TicketEmbedding`.
        """
        existing_result = await self.session.execute(
            select(TicketEmbedding).where(TicketEmbedding.ticket_id == ticket_id)
        )
        emb = existing_result.scalar_one_or_none()

        if emb is None:
            emb = TicketEmbedding(
                ticket_id=ticket_id,
                embedding=vector,
                model_version=model_version,
            )
            self.session.add(emb)
        else:
            emb.embedding = vector
            emb.model_version = model_version

        await self.session.flush()
        await self.session.refresh(emb)
        return emb

    async def find_similar(
        self,
        query_vector: list[float],
        top_k: int = 5,
        similarity_threshold: float = 0.0,
    ) -> list[SimilarTicketResult]:
        """Return the ``top_k`` most similar tickets using cosine distance.

        Uses the pgvector ``<=>`` operator (cosine distance) and the
        IVFFlat index for approximate nearest-neighbour search.

        Args:
            query_vector: 384-dimensional query embedding.
            top_k: Maximum number of results to return.
            similarity_threshold: Minimum cosine similarity; results below
                this threshold are excluded.

        Returns:
            Ranked list of :class:`SimilarTicketResult` from most to least similar.
        """
        result = await self.session.execute(
            text("""
                SELECT
                    te.ticket_id,
                    te.id,
                    1 - (te.embedding <=> CAST(:vec AS vector)) AS similarity
                FROM ticket_embeddings te
                WHERE 1 - (te.embedding <=> CAST(:vec AS vector)) >= :threshold
                ORDER BY te.embedding <=> CAST(:vec AS vector)
                LIMIT :top_k
            """),
            {
                "vec": str(query_vector),
                "threshold": similarity_threshold,
                "top_k": top_k,
            },
        )
        return [
            SimilarTicketResult(
                ticket_id=uuid.UUID(str(row.ticket_id)),
                embedding_id=uuid.UUID(str(row.id)),
                similarity_score=float(row.similarity),
            )
            for row in result.fetchall()
        ]
