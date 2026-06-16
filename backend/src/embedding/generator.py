"""Sentence-embedding generator wrapping all-MiniLM-L6-v2.

CPU-bound inference is always run in a thread pool via `asyncio.to_thread` so
it never blocks the event loop (audit fix H1, docs/03_BACKEND_DESIGN.md).
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import overload

import numpy as np
from sentence_transformers import SentenceTransformer

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _load_model(model_name: str) -> SentenceTransformer:
    logger.info("embedding_model_loading", model=model_name)
    model = SentenceTransformer(model_name)
    logger.info("embedding_model_ready", model=model_name)
    return model


class EmbeddingGenerator:
    """Thin async wrapper around SentenceTransformer.

    One instance per process is typical — the model is cached by `_load_model`.
    """

    def __init__(self, model_name: str | None = None, batch_size: int | None = None) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.embedding_model
        self._batch_size = batch_size or settings.embedding_batch_size

    def _encode_sync(self, texts: list[str]) -> np.ndarray:
        model = _load_model(self._model_name)
        return model.encode(  # type: ignore[no-any-return]
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    @overload
    async def encode(self, texts: str) -> list[float]: ...

    @overload
    async def encode(self, texts: list[str]) -> list[list[float]]: ...

    async def encode(self, texts: str | list[str]) -> list[float] | list[list[float]]:
        """Encode one or more texts; returns a flat list for a single string."""
        single = isinstance(texts, str)
        inputs = [texts] if single else texts
        vectors: np.ndarray = await asyncio.to_thread(self._encode_sync, inputs)
        result: list[list[float]] = vectors.tolist()
        return result[0] if single else result

    async def encode_one(self, text: str) -> list[float]:
        return await self.encode(text)


def build_embedding_generator() -> EmbeddingGenerator:
    return EmbeddingGenerator()
