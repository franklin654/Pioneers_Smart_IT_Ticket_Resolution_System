"""EmbeddingStore — generates and persists ticket embeddings.

Bridges ``EmbeddingGenerator`` (model inference) and ``EmbeddingRepository``
(database persistence) into a single service used by the ingestion pipeline
background task and the classifier training script.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.core.exceptions import EmbeddingError
from src.core.logging import get_logger
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.embedding.generator import EmbeddingGenerator

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)


class EmbeddingStore:
    """Generates and persists 384-dim embeddings for tickets.

    This class is a thin service layer — it does not own the DB session or
    the model; both are injected at construction time.

    Args:
        generator: Pre-loaded :class:`EmbeddingGenerator`.
        repo: :class:`EmbeddingRepository` bound to an active DB session.
        settings: Application settings (provides ``embedding_model`` name).
    """

    def __init__(
        self,
        generator: EmbeddingGenerator,
        repo: EmbeddingRepository,
        settings: "Settings",
    ) -> None:
        self._generator = generator
        self._repo = repo
        self._settings = settings

    async def embed_and_store(
        self,
        ticket_id: uuid.UUID,
        text: str,
    ) -> list[float]:
        """Generate an embedding for ``text`` and persist it to ``ticket_embeddings``.

        Uses the repository's ``upsert`` method so calling this twice for the
        same ticket updates the existing row rather than inserting a duplicate.

        Args:
            ticket_id: UUID of the parent ticket.
            text: Text to embed, typically
                ``f"{clean_title} {masked_description}"``.

        Returns:
            The 384-dim float vector that was stored.

        Raises:
            EmbeddingError: If model inference or the database write fails.
        """
        vector = self._generator.encode_single(text)

        await self._repo.upsert(
            ticket_id=ticket_id,
            vector=vector,
            model_version=self._settings.embedding_model,
        )

        logger.info(
            "Embedding stored",
            extra={
                "ticket_id": str(ticket_id),
                "metadata": {
                    "model": self._settings.embedding_model,
                    "vector_dim": len(vector),
                },
            },
        )
        return vector
