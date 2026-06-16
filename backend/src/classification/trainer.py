"""Classifier training: fetch labeled data → TF-IDF → fit LinearSVC + calibrate.

Uses a sklearn Pipeline (TfidfVectorizer → LinearSVC) + CalibratedClassifierCV.
TF-IDF consistently outperforms dense embeddings for LinearSVC on short text
with ~200 samples/class; embeddings are reserved for the RAG/near-dup path
where semantic similarity is the goal (docs/06_DATA_AND_EVALUATION.md).

Data access is strictly via `TicketRepository.get_training_data()` (audit fix
H3 from docs/03_BACKEND_DESIGN.md — no raw SQL or ORM queries here).
"""

from __future__ import annotations

import asyncio
import pickle
from dataclasses import dataclass
from pathlib import Path

from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from src.core.config import get_settings
from src.core.exceptions import AppBaseException
from src.core.logging import get_logger
from src.db.models import TicketCategory
from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)


class TrainingError(AppBaseException):
    code = "TRAINING_ERROR"
    http_status = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass
class TrainedClassifier:
    pipeline: Pipeline
    classes: list[TicketCategory]
    training_samples: int


def _fit_sync(texts: list[str], labels: list[str]) -> Pipeline:
    tfidf = TfidfVectorizer(
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=2,
        max_features=50_000,
        strip_accents="unicode",
    )
    svc = LinearSVC(C=1.0, max_iter=5000, dual="auto")
    calibrated = CalibratedClassifierCV(svc, cv=5, method="sigmoid")
    pipeline = Pipeline([("tfidf", tfidf), ("clf", calibrated)])
    pipeline.fit(texts, labels)
    return pipeline


async def train(ticket_repo: TicketRepository) -> TrainedClassifier:
    """Fetch training data, fit and return a calibrated TF-IDF + SVM classifier."""
    settings = get_settings()
    rows = await ticket_repo.get_training_data()

    if len(rows) < settings.classifier_min_samples:
        raise TrainingError(
            f"Only {len(rows)} training samples available; "
            f"need at least {settings.classifier_min_samples}."
        )

    texts = [f"{title} {description}" for title, description, _ in rows]
    labels = [cat.value for _, _, cat in rows]

    logger.info("classifier_fitting_start", samples=len(texts))
    pipeline = await asyncio.to_thread(_fit_sync, texts, labels)

    classes = [TicketCategory(c) for c in pipeline.classes_]
    logger.info("classifier_training_complete", samples=len(texts), classes=len(classes))

    return TrainedClassifier(pipeline=pipeline, classes=classes, training_samples=len(texts))


def save(trained: TrainedClassifier, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(trained, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("classifier_saved", path=str(path))


def load(path: Path) -> TrainedClassifier:
    if not path.exists():
        raise TrainingError(
            f"No trained classifier found at {path}. Run train_classifier.py first."
        )
    with path.open("rb") as f:
        trained: TrainedClassifier = pickle.load(f)  # noqa: S301
    logger.info("classifier_loaded", path=str(path), samples=trained.training_samples)
    return trained
