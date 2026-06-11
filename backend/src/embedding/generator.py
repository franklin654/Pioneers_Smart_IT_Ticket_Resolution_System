"""Sentence-transformer embedding generator.

Wraps ``sentence-transformers/all-MiniLM-L6-v2`` to produce 384-dimensional
L2-normalized float vectors for ticket text.  The model is loaded once at
construction time and reused for the process lifetime.

This class is the concrete implementation injected into:
    - ``Deduplicator`` (Phase 2) for near-duplicate detection
    - ``EmbeddingStore`` for persisting ticket embeddings
    - ``ClassifierTrainer`` and ``TicketClassifier`` for training and inference
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from sentence_transformers import SentenceTransformer

from src.core.exceptions import EmbeddingError
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)


class EmbeddingGenerator:
    """Generates 384-dimensional sentence embeddings.

    Uses ``sentence-transformers/all-MiniLM-L6-v2`` (80 MB, Apache 2.0).
    GPU is used automatically when available; falls back to CPU transparently.
    All output vectors are L2-normalized so cosine similarity equals dot product,
    which is required for the pgvector ``<=>`` operator to work correctly.

    Args:
        settings: Application settings; reads ``embedding_model`` and
            ``embedding_batch_size``.

    Raises:
        EmbeddingError: If the model cannot be loaded from disk or HuggingFace Hub.
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._model = self._load_model(settings.embedding_model)

    # ── Public API ─────────────────────────────────────────────────────────

    def encode_single(self, text: str) -> list[float]:
        """Encode one text string into a 384-dim L2-normalized vector.

        Args:
            text: Input text (e.g. ``title + " " + description``). Empty
                strings are accepted — the model returns a valid vector.

        Returns:
            List of 384 floats, L2-normalized (values in approximately [-1, 1]).

        Raises:
            EmbeddingError: If encoding fails for any reason.
        """
        try:
            vector: np.ndarray = self._model.encode(
                text,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return vector.tolist()
        except Exception as exc:
            raise EmbeddingError(
                message=f"Failed to encode text: {exc}",
                detail={"text_length": len(text), "error": str(exc)},
            ) from exc

    def encode_batch(
        self,
        texts: list[str],
        batch_size: int | None = None,
        show_progress: bool = False,
    ) -> list[list[float]]:
        """Encode a list of texts in batches.

        Args:
            texts: List of input strings. Empty lists return an empty list.
            batch_size: Overrides ``settings.embedding_batch_size`` when provided.
                Tuning this affects memory usage and throughput during training.
            show_progress: Display a tqdm progress bar. Useful in long-running
                training scripts but noisy in production.

        Returns:
            List of 384-dim float vectors, one per input text, in the same order.

        Raises:
            EmbeddingError: If encoding fails for any reason.
        """
        if not texts:
            return []

        effective_batch_size = batch_size or self._settings.embedding_batch_size

        try:
            vectors: np.ndarray = self._model.encode(
                texts,
                batch_size=effective_batch_size,
                normalize_embeddings=True,
                show_progress_bar=show_progress,
                convert_to_numpy=True,
            )
            return [v.tolist() for v in vectors]
        except Exception as exc:
            raise EmbeddingError(
                message=f"Failed to batch-encode {len(texts)} texts: {exc}",
                detail={"text_count": len(texts), "batch_size": effective_batch_size, "error": str(exc)},
            ) from exc

    @property
    def model_name(self) -> str:
        """Return the model identifier string from settings."""
        return self._settings.embedding_model

    @property
    def embedding_dim(self) -> int:
        """Return the expected vector dimension."""
        return self._settings.embedding_dim

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _load_model(model_name: str) -> SentenceTransformer:
        """Load the SentenceTransformer model.

        Args:
            model_name: HuggingFace model identifier or local path.

        Returns:
            Loaded ``SentenceTransformer`` instance.

        Raises:
            EmbeddingError: If the model cannot be loaded.
        """
        try:
            logger.info(
                "Loading embedding model",
                extra={"metadata": {"model": model_name}},
            )
            model = SentenceTransformer(model_name)
            logger.info(
                "Embedding model loaded",
                extra={"metadata": {"model": model_name}},
            )
            return model
        except Exception as exc:
            raise EmbeddingError(
                message=f"Failed to load embedding model '{model_name}': {exc}",
                detail={"model": model_name, "error": str(exc)},
            ) from exc
