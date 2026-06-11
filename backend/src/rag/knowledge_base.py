"""Knowledge base management for the RAG pipeline.

Handles two indexes:
    1. **pgvector dense index** — 384-dim embeddings on ``knowledge_base_entries``
       already created by ``scripts/index_knowledge_base.py``.
    2. **BM25 sparse index** — in-memory ``rank-bm25`` index built at startup
       from all KB entries.  Serialized to disk so it survives restarts without
       a full rebuild.

The knowledge base is also updated when an agent accepts or modifies a
generated resolution — accepted resolutions become new KB entries that
improve future retrieval.
"""

from __future__ import annotations

import asyncio
import pickle
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.logging import get_logger
from src.db.models import FeedbackAction, KnowledgeBaseEntry, TicketCategory
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository

if TYPE_CHECKING:
    from src.core.config import Settings
    from src.embedding.generator import EmbeddingGenerator

logger = get_logger(__name__)

_BM25_INDEX_FILENAME = "bm25_index.pkl"


def _load_pickle(path: Path) -> dict:
    with open(path, "rb") as f:
        return pickle.load(f)  # noqa: S301


def _save_pickle(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(data, f)


class KnowledgeBase:
    """Manages the RAG knowledge base: dense (pgvector) and sparse (BM25) indexes.

    At startup, call ``build_bm25_index()`` to load all KB entries and
    construct the in-memory BM25 index.  The dense index is already stored
    in PostgreSQL and requires no extra initialization.

    Args:
        repo: :class:`KnowledgeBaseRepository` bound to an active DB session.
        embedding_generator: Used when adding new entries from agent feedback.
        settings: Application settings.
    """

    def __init__(
        self,
        repo: KnowledgeBaseRepository,
        embedding_generator: "EmbeddingGenerator",
        settings: "Settings",
    ) -> None:
        self._repo = repo
        self._generator = embedding_generator
        self._settings = settings
        self._bm25_index = None        # built lazily or loaded from disk
        self._bm25_entries: list[KnowledgeBaseEntry] = []   # parallel list

    # ── Public API ─────────────────────────────────────────────────────────

    async def build_bm25_index(self, force_rebuild: bool = False) -> None:
        """Load all KB entries and build the in-memory BM25 index.

        If a serialized index exists on disk and ``force_rebuild`` is False,
        the cached version is loaded instead of re-building from scratch.

        Args:
            force_rebuild: If True, always rebuild from the database.
        """
        from rank_bm25 import BM25Okapi

        cache_path = Path(self._settings.model_dir) / _BM25_INDEX_FILENAME

        if not force_rebuild and cache_path.exists():
            try:
                cached = await asyncio.to_thread(_load_pickle, cache_path)
                self._bm25_index = cached["index"]
                self._bm25_entries = cached["entries"]
                logger.info(
                    "BM25 index loaded from cache",
                    extra={"metadata": {"entries": len(self._bm25_entries)}},
                )
                return
            except (OSError, EOFError, pickle.UnpicklingError) as exc:
                logger.warning(
                    "BM25 cache load failed — rebuilding",
                    extra={"metadata": {"error": str(exc)}},
                )

        entries = await self._repo.get_all_for_bm25(limit=50_000)
        if not entries:
            logger.warning("No KB entries found — BM25 index will be empty")
            self._bm25_entries = []
            self._bm25_index = BM25Okapi([[]])
            return

        tokenized = [self._tokenize(f"{e.title} {e.resolution}") for e in entries]
        self._bm25_index = BM25Okapi(tokenized)
        self._bm25_entries = entries

        # Persist to disk for fast restarts
        await asyncio.to_thread(
            _save_pickle, cache_path, {"index": self._bm25_index, "entries": entries}
        )

        logger.info(
            "BM25 index built and cached",
            extra={"metadata": {"entries": len(entries), "cache": str(cache_path)}},
        )

    async def add_from_feedback(
        self,
        ticket_title: str,
        ticket_description: str,
        category: TicketCategory,
        resolution: str,
        action: FeedbackAction,
    ) -> None:
        """Add or update a KB entry based on agent feedback.

        Only ``ACCEPTED`` and ``MODIFIED`` actions add to the knowledge base.
        ``REJECTED`` resolutions are discarded.

        Args:
            ticket_title: Original ticket title.
            ticket_description: Masked ticket description.
            category: Ticket category (used for filtered retrieval).
            resolution: The resolution text to store (accepted or modified).
            action: Feedback action (ACCEPTED / MODIFIED / REJECTED).
        """
        if action == FeedbackAction.REJECTED:
            return

        embedding = await asyncio.to_thread(
            self._generator.encode_single, f"{ticket_title} {ticket_description}"
        )
        entry = KnowledgeBaseEntry(
            title=ticket_title,
            description=ticket_description,
            category=category,
            resolution=resolution,
            embedding=embedding,
            source="agent_feedback",
        )
        await self._repo.create(entry)

        # Invalidate the BM25 cache so next startup rebuilds with new entry
        cache_path = Path(self._settings.model_dir) / _BM25_INDEX_FILENAME
        if cache_path.exists():
            cache_path.unlink(missing_ok=True)

        logger.info(
            "KB entry added from feedback",
            extra={"metadata": {"category": category.value, "action": action.value}},
        )

    def get_bm25_index(self):
        """Return the built BM25 index.  Returns None if not yet built."""
        return self._bm25_index

    def get_bm25_entries(self) -> list[KnowledgeBaseEntry]:
        """Return the KB entries parallel to the BM25 index."""
        return self._bm25_entries

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple whitespace tokenizer for BM25.  Lowercases and splits."""
        return text.lower().split()
