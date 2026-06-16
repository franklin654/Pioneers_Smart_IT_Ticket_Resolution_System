"""BM25 index management for the RAG pipeline's sparse retrieval leg.

The index is built from `knowledge_base_entries` rows and held in memory.
All pickle I/O is wrapped in `asyncio.to_thread` (audit fix M2) since pickle
serialisation/deserialisation blocks the event loop on large corpora.
"""

from __future__ import annotations

import asyncio
import pickle
from pathlib import Path
from typing import TYPE_CHECKING

from rank_bm25 import BM25Okapi

from src.core.logging import get_logger
from src.db.models import KnowledgeBaseEntry, TicketCategory

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class KnowledgeBaseIndex:
    """In-memory BM25 index over KB entries, with category-filtered lookup."""

    def __init__(
        self, entries: list[KnowledgeBaseEntry], index: BM25Okapi, corpus: list[str]
    ) -> None:
        self._entries = entries
        self._index = index
        self._corpus = corpus

    @classmethod
    def build(cls, entries: list[KnowledgeBaseEntry]) -> KnowledgeBaseIndex:
        corpus = [f"{e.title} {e.description}" for e in entries]
        if not corpus:
            raise ValueError("Cannot build BM25 index from an empty corpus.")
        tokenized = [_tokenize(doc) for doc in corpus]
        index = BM25Okapi(tokenized)
        logger.info("bm25_index_built", entries=len(entries))
        return cls(entries, index, corpus)

    def search(
        self,
        query: str,
        top_k: int = 20,
        category_filter: TicketCategory | None = None,
    ) -> list[tuple[KnowledgeBaseEntry, float]]:
        tokens = _tokenize(query)
        scores = self._index.get_scores(tokens)

        results: list[tuple[KnowledgeBaseEntry, float]] = []
        for entry, score in zip(self._entries, scores, strict=False):
            if category_filter is not None and entry.category != category_filter:
                continue
            results.append((entry, float(score)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    @property
    def size(self) -> int:
        return len(self._entries)


async def build_index(entries: list[KnowledgeBaseEntry]) -> KnowledgeBaseIndex:
    return await asyncio.to_thread(KnowledgeBaseIndex.build, entries)


async def save_index(index: KnowledgeBaseIndex, path: Path) -> None:
    def _save() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)

    await asyncio.to_thread(_save)
    logger.info("bm25_index_saved", path=str(path))


async def load_index(path: Path) -> KnowledgeBaseIndex:
    def _load() -> KnowledgeBaseIndex:
        with path.open("rb") as f:
            return pickle.load(f)  # noqa: S301

    index: KnowledgeBaseIndex = await asyncio.to_thread(_load)
    logger.info("bm25_index_loaded", path=str(path), entries=index.size)
    return index
