"""Real-time ticket classifier backed by a pre-trained LinearSVC (calibrated).

Loads a serialized ``TrainedModelArtifact`` produced by ``ClassifierTrainer``
and performs low-latency inference (target < 22ms).  Thread-safe for
concurrent reads — sklearn's ``predict_proba`` is read-only after training.

Usage::

    classifier = TicketClassifier.from_settings(settings)
    output = classifier.predict("VPN is down, user cannot authenticate")
    print(output.predicted_category, output.confidence_level)
"""

from __future__ import annotations

import joblib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.classification.confidence import ClassificationOutput, ConfidenceScorer
from src.core.exceptions import ClassificationError
from src.core.logging import get_logger
from src.db.models import TicketCategory
from src.embedding.generator import EmbeddingGenerator

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)


@dataclass
class TrainedModelArtifact:
    """Serialized model bundle produced by :class:`ClassifierTrainer`.

    Attributes:
        pipeline: Fitted sklearn ``Pipeline`` containing the
            ``CalibratedClassifierCV(LinearSVC)`` estimator.
        label_encoder: Fitted ``LabelEncoder`` mapping integer class indices
            to :class:`~src.db.models.TicketCategory` string values.
        model_version: Unique identifier for this training run,
            e.g. ``"linearsvc_v20260602_143012"``.
        trained_at: ISO-8601 UTC timestamp of when training completed.
        training_samples: Number of examples the model was trained on.
        categories: Ordered list of category values matching the label encoder
            order (same as ``label_encoder.classes_``).
    """

    pipeline: Any          # sklearn Pipeline — typed as Any to avoid sklearn import at top-level
    label_encoder: Any     # sklearn LabelEncoder
    model_version: str
    trained_at: str
    training_samples: int
    categories: list[str]


class TicketClassifier:
    """Classifies tickets using a pre-trained LinearSVC (calibrated) model.

    The embedding generation and classification are two separate steps:
        1. ``EmbeddingGenerator.encode_single(text)`` → 384-dim vector
        2. ``pipeline.predict_proba([vector])`` → probability array
        3. ``ConfidenceScorer.score(probs)`` → ``ClassificationOutput``

    Args:
        model_path: Path to the ``.pkl`` artifact produced by
            :class:`ClassifierTrainer`.
        settings: Application settings (thresholds + model name).
        embedding_generator: Optional pre-built generator.  When ``None``,
            a new ``EmbeddingGenerator`` is constructed from ``settings``
            on first ``predict()`` call.

    Raises:
        ClassificationError: If the model file cannot be loaded or is corrupt.
    """

    MODEL_FILENAME: str = "classifier.pkl"

    def __init__(
        self,
        model_path: Path,
        settings: "Settings",
        embedding_generator: EmbeddingGenerator | None = None,
    ) -> None:
        self._settings = settings
        self._artifact = self._load_artifact(model_path)
        self._scorer = ConfidenceScorer(settings)
        # Lazy-initialize the embedding generator to avoid loading the model
        # when the classifier itself is being tested with mocked artifacts.
        self._embedding_generator = embedding_generator

    def predict(self, text: str) -> ClassificationOutput:
        """Classify a single ticket and return a fully scored output.

        Args:
            text: Combined ticket text, typically
                ``f"{clean_title} {masked_description}"``.

        Returns:
            :class:`ClassificationOutput` with category, confidence, and
            multi-domain flag populated.

        Raises:
            ClassificationError: If embedding or classification fails.
        """
        try:
            generator = self._get_embedding_generator()
            vector = generator.encode_single(text)

            proba = self._artifact.pipeline.predict_proba([vector])[0]
            category_probabilities = self._build_probability_map(proba)

            output = self._scorer.score(
                category_probabilities=category_probabilities,
                classification_method=self._artifact.model_version,
            )

            logger.info(
                "Ticket classified",
                extra={
                    "metadata": {
                        "predicted_category": output.predicted_category.value,
                        "confidence": output.confidence,
                        "confidence_level": output.confidence_level.value,
                        "is_multi_domain": output.is_multi_domain,
                    }
                },
            )
            return output

        except ClassificationError:
            raise
        except Exception as exc:
            raise ClassificationError(
                message=f"Classification failed: {exc}",
                detail={"error": str(exc)},
            ) from exc

    @classmethod
    def from_settings(
        cls,
        settings: "Settings",
        embedding_generator: EmbeddingGenerator | None = None,
    ) -> "TicketClassifier":
        """Construct a :class:`TicketClassifier` using the path from settings.

        Args:
            settings: Application settings; reads ``model_dir`` to find the
                artifact file.
            embedding_generator: Optional pre-built generator to share.

        Returns:
            Loaded and ready-to-use :class:`TicketClassifier`.

        Raises:
            ClassificationError: If the model file does not exist or is corrupt.
        """
        model_path = Path(settings.model_dir) / cls.MODEL_FILENAME
        return cls(
            model_path=model_path,
            settings=settings,
            embedding_generator=embedding_generator,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _get_embedding_generator(self) -> EmbeddingGenerator:
        """Lazy-initialize the EmbeddingGenerator on first call."""
        if self._embedding_generator is None:
            self._embedding_generator = EmbeddingGenerator(self._settings)
        return self._embedding_generator

    def _build_probability_map(
        self, proba: "Any"
    ) -> dict[TicketCategory, float]:
        """Convert the classifier's probability array to a category → prob dict.

        The label encoder's ``classes_`` attribute defines the mapping from
        array position to category string, which is identical to
        ``artifact.categories``.

        Args:
            proba: 1-D numpy array of class probabilities from
                ``predict_proba``.

        Returns:
            Dict mapping each :class:`TicketCategory` to its probability.
        """
        return {
            TicketCategory(cat): float(prob)
            for cat, prob in zip(self._artifact.categories, proba)
        }

    @staticmethod
    def _load_artifact(model_path: Path) -> TrainedModelArtifact:
        """Deserialize the model artifact from disk.

        Args:
            model_path: Absolute or relative path to the ``.pkl`` file.

        Returns:
            Loaded :class:`TrainedModelArtifact`.

        Raises:
            ClassificationError: If the file is missing, unreadable, or not a
                valid :class:`TrainedModelArtifact`.
        """
        if not model_path.exists():
            raise ClassificationError(
                message=f"Model file not found: {model_path}",
                detail={"model_path": str(model_path)},
            )

        try:
            artifact = joblib.load(model_path)
            if not isinstance(artifact, TrainedModelArtifact):
                raise ClassificationError(
                    message="Loaded object is not a TrainedModelArtifact",
                    detail={"type": type(artifact).__name__, "model_path": str(model_path)},
                )
            logger.info(
                "Classifier model loaded",
                extra={
                    "metadata": {
                        "model_version": artifact.model_version,
                        "training_samples": artifact.training_samples,
                        "trained_at": artifact.trained_at,
                    }
                },
            )
            return artifact
        except ClassificationError:
            raise
        except Exception as exc:
            raise ClassificationError(
                message=f"Failed to load model from {model_path}: {exc}",
                detail={"model_path": str(model_path), "error": str(exc)},
            ) from exc
