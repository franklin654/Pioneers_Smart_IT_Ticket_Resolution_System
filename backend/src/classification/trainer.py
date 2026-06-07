"""Classifier training pipeline.

Trains a LinearSVC (wrapped in CalibratedClassifierCV) on sentence-transformer
embeddings of labeled IT support tickets.  Produces a serialized
``TrainedModelArtifact`` that ``TicketClassifier`` can load for real-time
inference.

Workflow:
    1. Load all labeled tickets from the database (``category IS NOT NULL``)
    2. Build text = ``"{title} {description}"`` for each ticket
    3. Batch-generate embeddings via ``EmbeddingGenerator``
    4. Stratified 80/20 train/test split
    5. Fit ``LinearSVC`` wrapped in ``CalibratedClassifierCV`` (cv=3) so that
       ``predict_proba`` is available for confidence scoring
    6. Evaluate: accuracy, macro F1, per-class F1, confusion matrix
    7. Serialize ``TrainedModelArtifact`` with ``joblib``

Usage::

    python -m scripts.train_classifier
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.classification.classifier import TrainedModelArtifact
from src.core.exceptions import ClassificationError
from src.core.logging import get_logger
from src.db.models import TicketCategory
from src.db.repositories.ticket_repo import TicketRepository, TicketSearchFilters
from src.embedding.generator import EmbeddingGenerator

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)

# Canonical label order — fitted on ALL 6 categories so the label encoder
# is stable even when some categories are under-represented in training data.
ALL_CATEGORIES: list[str] = [c.value for c in TicketCategory]


@dataclass
class TrainingConfig:
    """Hyperparameters and I/O paths for a training run.

    Attributes:
        C: Inverse of regularization strength (sklearn convention).
            Smaller → stronger regularization.
        max_iter: Max solver iterations; increase if convergence warnings appear.
        random_state: Fixed seed for reproducibility.
        test_size: Fraction of data held out for evaluation.
        stratify: Keep class proportions equal in train/test splits.
        model_output_path: Where to write the serialized artifact.
    """

    C: float = 1.0
    max_iter: int = 1000
    class_weight: str = "balanced"
    random_state: int = 42
    test_size: float = 0.20
    stratify: bool = True
    model_output_path: Path = Path("data/models/classifier.pkl")


@dataclass
class TrainingResult:
    """Metrics and metadata from a completed training run.

    Attributes:
        accuracy: Fraction of test-set predictions that were correct.
        macro_f1: Unweighted mean F1 across all categories.
        per_class_f1: Per-category F1 scores; keys are category string values.
        confusion_matrix: ``num_classes × num_classes`` list of lists.
        training_samples: Number of tickets used for training.
        test_samples: Number of tickets used for evaluation.
        model_path: Absolute path to the saved ``.pkl`` file.
        model_version: Unique version string embedded in the artifact.
    """

    accuracy: float
    macro_f1: float
    per_class_f1: dict[str, float]
    confusion_matrix: list[list[int]]
    training_samples: int
    test_samples: int
    model_path: Path
    model_version: str


class ClassifierTrainer:
    """Trains a LinearSVC classifier on ticket embeddings.

    Args:
        embedding_generator: Pre-loaded :class:`EmbeddingGenerator`.
        ticket_repo: :class:`TicketRepository` bound to an active DB session.
        settings: Application settings.
        config: Training hyperparameters; uses defaults if ``None``.
    """

    def __init__(
        self,
        embedding_generator: EmbeddingGenerator,
        ticket_repo: TicketRepository,
        settings: "Settings",
        config: TrainingConfig | None = None,
    ) -> None:
        self._generator = embedding_generator
        self._ticket_repo = ticket_repo
        self._settings = settings
        self._config = config or TrainingConfig()

    async def train(self) -> TrainingResult:
        """Run the full training pipeline.

        Returns:
            :class:`TrainingResult` with evaluation metrics and model path.

        Raises:
            ClassificationError: If there are fewer than
                ``settings.classifier_min_samples`` labeled tickets, or if
                any training step fails.
        """
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import LabelEncoder

        # ── Step 1: Load data ──────────────────────────────────────────────
        texts, labels = await self._load_training_data()
        total = len(texts)

        if total < self._settings.classifier_min_samples:
            raise ClassificationError(
                message=(
                    f"Not enough labeled tickets to train: found {total}, "
                    f"need at least {self._settings.classifier_min_samples}."
                ),
                detail={"found": total, "required": self._settings.classifier_min_samples},
            )

        logger.info(
            "Training data loaded",
            extra={"metadata": {"total_samples": total, "categories": list(set(labels))}},
        )

        # ── Step 2: Embed ──────────────────────────────────────────────────
        embeddings = self._encode_all(texts)

        # ── Step 3: Encode labels & split ──────────────────────────────────
        label_encoder = LabelEncoder()
        label_encoder.fit(ALL_CATEGORIES)  # fit on ALL categories for stability
        y_encoded = label_encoder.transform(labels)

        X_train, X_test, y_train, y_test = train_test_split(
            embeddings,
            y_encoded,
            test_size=self._config.test_size,
            random_state=self._config.random_state,
            stratify=y_encoded if self._config.stratify else None,
        )

        # ── Step 4: Train ──────────────────────────────────────────────────
        from sklearn.svm import LinearSVC
        from sklearn.calibration import CalibratedClassifierCV

        logger.info("Fitting LinearSVC + CalibratedClassifierCV")
        svc = LinearSVC(
            C=self._config.C,
            max_iter=self._config.max_iter,
            class_weight=self._config.class_weight,
            random_state=self._config.random_state,
        )
        # Wrap in CalibratedClassifierCV so predict_proba is available (needed
        # for confidence scores and multi-domain detection in TicketClassifier).
        calibrated = CalibratedClassifierCV(svc, cv=3)
        pipeline = Pipeline(steps=[("clf", calibrated)])
        pipeline.fit(X_train, y_train)

        # ── Step 5: Evaluate ───────────────────────────────────────────────
        metrics = self._evaluate(pipeline, label_encoder, X_test, list(y_test))

        # ── Step 6: Save ───────────────────────────────────────────────────
        model_version = f"linearsvc_v{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        saved_path = self._save_artifact(
            pipeline=pipeline,
            label_encoder=label_encoder,
            categories=list(label_encoder.classes_),
            training_samples=len(X_train),
            model_version=model_version,
        )

        logger.info(
            "Training complete",
            extra={
                "metadata": {
                    "accuracy": metrics["accuracy"],
                    "macro_f1": metrics["macro_f1"],
                    "model_path": str(saved_path),
                }
            },
        )

        return TrainingResult(
            accuracy=metrics["accuracy"],
            macro_f1=metrics["macro_f1"],
            per_class_f1=metrics["per_class_f1"],
            confusion_matrix=metrics["confusion_matrix"],
            training_samples=len(X_train),
            test_samples=len(X_test),
            model_path=saved_path,
            model_version=model_version,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    async def _load_training_data(self) -> tuple[list[str], list[str]]:
        """Load labeled tickets from the database, excluding WEBHOOK (held-out) tickets.

        Returns:
            Tuple ``(texts, labels)`` where ``texts[i]`` is the combined
            ``title + description`` and ``labels[i]`` is the category string.
        """
        labeled = await self._ticket_repo.get_training_data(limit=200_000)
        texts = [f"{t.title} {t.description}" for t in labeled]
        labels = [t.category.value for t in labeled]
        return texts, labels

    def _encode_all(self, texts: list[str]) -> list[list[float]]:
        """Batch-encode all texts with a progress bar."""
        return self._generator.encode_batch(texts, show_progress=True)

    def _evaluate(
        self,
        pipeline: "Any",
        label_encoder: "Any",
        X_test: list[list[float]],
        y_test: list[int],
    ) -> dict:
        """Compute classification metrics on the test set.

        Returns:
            Dict with keys: accuracy, macro_f1, per_class_f1, confusion_matrix.
        """
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
        )

        y_pred = pipeline.predict(X_test)
        accuracy = float(accuracy_score(y_test, y_pred))

        sorted_cats = list(label_encoder.classes_)
        report = classification_report(
            y_test,
            y_pred,
            labels=list(range(len(sorted_cats))),
            target_names=sorted_cats,
            output_dict=True,
            zero_division=0,
        )
        macro_f1 = float(report["macro avg"]["f1-score"])
        per_class_f1 = {
            cat: float(report[cat]["f1-score"])
            for cat in sorted_cats
            if cat in report
        }

        cm = confusion_matrix(y_test, y_pred, labels=list(range(len(sorted_cats))))

        return {
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "per_class_f1": per_class_f1,
            "confusion_matrix": cm.tolist(),
        }

    def _save_artifact(
        self,
        pipeline: "Any",
        label_encoder: "Any",
        categories: list[str],
        training_samples: int,
        model_version: str,
    ) -> Path:
        """Serialize the trained model to disk with joblib.

        Creates the output directory if it does not exist.

        Returns:
            Absolute path to the saved file.
        """
        import joblib

        output_path = self._config.model_output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        artifact = TrainedModelArtifact(
            pipeline=pipeline,
            label_encoder=label_encoder,
            model_version=model_version,
            trained_at=datetime.now(UTC).isoformat(),
            training_samples=training_samples,
            categories=categories,
        )

        joblib.dump(artifact, output_path)
        return output_path.resolve()
