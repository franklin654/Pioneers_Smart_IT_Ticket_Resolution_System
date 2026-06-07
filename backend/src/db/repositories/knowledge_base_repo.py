"""Repository for KnowledgeBaseEntry with bulk operations and vector search."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text

from src.core.logging import get_logger
from src.db.models import KnowledgeBaseEntry, TicketCategory
from src.db.repositories.base_repo import BaseRepository

logger = get_logger(__name__)

# Two static query variants — avoids f-string SQL construction.
# pgvector's <=> operator is not available in SQLAlchemy's ORM layer.
_SEARCH_SQL = text("""
    SELECT
        kbe.id,
        kbe.title,
        kbe.resolution,
        kbe.category,
        1 - (kbe.embedding <=> CAST(:vec AS vector)) AS similarity
    FROM knowledge_base_entries kbe
    ORDER BY kbe.embedding <=> CAST(:vec AS vector)
    LIMIT :top_k
""")

_SEARCH_SQL_WITH_CATEGORY = text("""
    SELECT
        kbe.id,
        kbe.title,
        kbe.resolution,
        kbe.category,
        1 - (kbe.embedding <=> CAST(:vec AS vector)) AS similarity
    FROM knowledge_base_entries kbe
    WHERE kbe.category = :category
    ORDER BY kbe.embedding <=> CAST(:vec AS vector)
    LIMIT :top_k
""")


@dataclass
class SimilarKBResult:
    """Result item from an ANN similarity search against the knowledge base."""

    entry_id: uuid.UUID
    title: str
    resolution: str
    category: TicketCategory
    similarity_score: float  # cosine similarity in range [0, 1]


class KnowledgeBaseRepository(BaseRepository[KnowledgeBaseEntry]):
    """Repository for :class:`~src.db.models.KnowledgeBaseEntry`.

    Extends :class:`BaseRepository` with bulk insertion, BM25 data loading,
    and embedding-based similarity search.
    """

    model_class = KnowledgeBaseEntry

    async def bulk_insert(self, entries: list[KnowledgeBaseEntry]) -> int:
        """Insert a batch of knowledge base entries.

        Adds all entries to the session and flushes once for efficiency.
        The caller is responsible for committing the transaction.

        Args:
            entries: List of :class:`KnowledgeBaseEntry` objects to insert.

        Returns:
            Number of entries added (equals ``len(entries)``).
        """
        self.session.add_all(entries)
        await self.session.flush()
        return len(entries)

    async def get_all_for_bm25(self, limit: int = 50_000) -> list[KnowledgeBaseEntry]:
        """Load KB entries to build the in-memory BM25 index.

        This is called once at startup by the RAG pipeline to construct
        the ``rank-bm25`` index over all resolutions.

        Args:
            limit: Maximum entries to load. Default 50,000 prevents OOM on
                large corpora. A warning is logged if the cap is hit.

        Returns:
            :class:`KnowledgeBaseEntry` rows (unordered), up to ``limit``.
        """
        result = await self.session.execute(
            select(KnowledgeBaseEntry).limit(limit)
        )
        entries = list(result.scalars().all())
        if len(entries) >= limit:
            logger.warning(
                "get_all_for_bm25 hit the row cap — BM25 index may be incomplete",
                extra={"metadata": {"limit": limit}},
            )
        return entries

    async def update_embedding(
        self, entry_id: uuid.UUID, vector: list[float]
    ) -> None:
        """Store a pre-computed embedding for a knowledge base entry.

        Called by ``scripts/index_knowledge_base.py`` after generating
        embeddings for entries that were inserted without vectors.

        Args:
            entry_id: UUID of the knowledge base entry to update.
            vector: 384-dimensional float list.
        """
        entry = await self.get_by_id(entry_id)
        if entry is not None:
            entry.embedding = vector
            await self.session.flush()

    async def search_similar(
        self,
        query_vector: list[float],
        top_k: int = 10,
        category_filter: TicketCategory | None = None,
    ) -> list[SimilarKBResult]:
        """Return the most similar knowledge base entries using cosine distance.

        Optionally restricts results to a single category for precision.
        Uses the pgvector ``<=>`` cosine distance operator and the
        IVFFlat index.

        Args:
            query_vector: 384-dimensional query embedding.
            top_k: Maximum results to return.
            category_filter: If provided, only entries in this category
                are considered.

        Returns:
            Ranked list of :class:`SimilarKBResult` from most to least similar.
        """
        params: dict = {"vec": str(query_vector), "top_k": top_k}
        if category_filter is not None:
            # DB enum stores uppercase names (e.g. "APPLICATION"), not lowercase .value
            params["category"] = category_filter.name
            sql = _SEARCH_SQL_WITH_CATEGORY
        else:
            sql = _SEARCH_SQL
        result = await self.session.execute(sql, params)
        return [
            SimilarKBResult(
                entry_id=uuid.UUID(str(row.id)),
                title=row.title,
                resolution=row.resolution,
                category=TicketCategory(row.category.lower()),
                similarity_score=float(row.similarity),
            )
            for row in result.fetchall()
        ]
