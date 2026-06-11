"""Stage 3 of the ingestion pipeline: duplicate detection.

Two-pass deduplication strategy:

    Pass 1 — Exact match
        Compute SHA-256 hash of normalized (title + description) and check
        against the ``tickets.content_hash`` unique index. One indexed
        DB read; O(1) cost.

    Pass 2 — Near-duplicate (semantic similarity)
        Generate a sentence-transformer embedding for the incoming ticket
        and search pgvector for similar tickets within the dedup window.
        If the nearest neighbour's cosine similarity ≥ the configured
        threshold, the ticket is treated as a near-duplicate.

SHA-256 is used instead of MD5 because:
    - Avoids security linter warnings (ruff S324 / bandit B324)
    - Better collision resistance (negligible for this use case but free)
    - No functional downside for deduplication

Pass 2 is skipped gracefully if:
    - No ``embedding_generator`` was injected (``None``).
    - The embedding generator raises any exception.

This keeps Phase 2 independently runnable without Phase 3 (EmbeddingGenerator).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.core.exceptions import EmbeddingError
from src.core.logging import get_logger
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.ticket_repo import TicketRepository

if TYPE_CHECKING:
    from src.core.config import Settings
    from src.ingestion.pipeline import IngestionContext

logger = get_logger(__name__)


@dataclass
class DuplicateCheckResult:
    """Outcome of the two-pass deduplication check.

    Attributes:
        is_duplicate: True if the ticket matches an existing one.
        duplicate_type: ``"exact"`` (hash match) or ``"near"``
            (embedding similarity) when ``is_duplicate`` is True; else None.
        existing_ticket_id: String UUID of the matching ticket, or None.
        content_hash: SHA-256 hash computed for this ticket regardless of
            duplicate status.
    """

    is_duplicate: bool
    duplicate_type: str | None
    existing_ticket_id: str | None
    content_hash: str


class Deduplicator:
    """Detects exact and near-duplicate incoming tickets.

    Designed for dependency injection: all external dependencies
    (repositories, embedding generator, settings) are passed at
    construction time so the class is easily testable with mocks.

    Args:
        ticket_repo: Repository for querying existing tickets by hash.
        embedding_repo: Repository for ANN similarity search via pgvector.
        embedding_generator: Optional embedding model; if ``None``, near-
            duplicate detection is skipped.
        settings: Application settings; provides threshold and window values.
    """

    def __init__(
        self,
        ticket_repo: TicketRepository,
        embedding_repo: EmbeddingRepository,
        embedding_generator: Any | None,
        settings: "Settings",
    ) -> None:
        self._ticket_repo = ticket_repo
        self._embedding_repo = embedding_repo
        self._embedding_generator = embedding_generator
        self._settings = settings

    async def check(self, ctx: "IngestionContext") -> DuplicateCheckResult:
        """Run both deduplication passes and return the combined result.

        Exact matching is always performed.  Near-duplicate detection is
        attempted only when an embedding generator is available; failures
        are swallowed so ingestion is never blocked by embedding errors.

        Args:
            ctx: Context with ``clean_title`` and ``clean_description``
                populated by Stage 1 (validator).

        Returns:
            :class:`DuplicateCheckResult` with all fields populated.
        """
        title = ctx.clean_title or ctx.raw_title
        description = ctx.clean_description or ctx.raw_description

        content_hash = TicketRepository.compute_content_hash(title, description)

        # ── Pass 1: exact match ────────────────────────────────────────────
        existing_id = await self._check_exact(content_hash)
        if existing_id:
            logger.info(
                "Exact duplicate detected",
                extra={"metadata": {"existing_ticket_id": existing_id}},
            )
            return DuplicateCheckResult(
                is_duplicate=True,
                duplicate_type="exact",
                existing_ticket_id=existing_id,
                content_hash=content_hash,
            )

        # ── Pass 2: near-duplicate via embedding similarity ────────────────
        combined_text = f"{title} {description}"
        existing_id = await self._check_near(combined_text)
        if existing_id:
            logger.info(
                "Near-duplicate detected",
                extra={"metadata": {"existing_ticket_id": existing_id}},
            )
            return DuplicateCheckResult(
                is_duplicate=True,
                duplicate_type="near",
                existing_ticket_id=existing_id,
                content_hash=content_hash,
            )

        return DuplicateCheckResult(
            is_duplicate=False,
            duplicate_type=None,
            existing_ticket_id=None,
            content_hash=content_hash,
        )

    # ── Private helpers ───────────────────────────────────────────────────

    async def _check_exact(self, content_hash: str) -> str | None:
        """Return the string UUID of an existing ticket with the same hash.

        Args:
            content_hash: SHA-256 hex digest of normalized title + description.

        Returns:
            String UUID if a match is found, else ``None``.
        """
        ticket = await self._ticket_repo.get_by_hash(content_hash)
        return str(ticket.id) if ticket is not None else None

    async def _check_near(self, text: str) -> str | None:
        """Generate an embedding and search for semantically similar tickets.

        Near-duplicate detection is skipped (returns ``None``) when:
            - ``self._embedding_generator`` is ``None``
            - The generator raises any exception

        Args:
            text: Combined ``title + description`` string to encode.

        Returns:
            String UUID of the nearest matching ticket, or ``None``.
        """
        if self._embedding_generator is None:
            return None

        try:
            vector: list[float] = self._embedding_generator.encode_single(text)
        except EmbeddingError as exc:
            logger.warning(
                "Embedding generation failed — skipping near-duplicate check",
                extra={"metadata": {"error": str(exc)}},
            )
            return None
        except Exception as exc:
            logger.warning(
                "Unexpected error during near-duplicate embedding — skipping",
                extra={"metadata": {"error": str(exc)}},
            )
            return None

        results = await self._embedding_repo.find_similar(
            query_vector=vector,
            top_k=1,
            similarity_threshold=self._settings.dedup_similarity_threshold,
        )

        if not results:
            return None

        return str(results[0].ticket_id)
