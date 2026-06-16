"""TicketClassifier: run TF-IDF pipeline → predict probabilities → score confidence.

Inference runs in asyncio.to_thread (audit fix H1).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from src.classification.confidence import ConfidenceResult, score
from src.classification.trainer import TrainedClassifier
from src.classification.trainer import load as load_trained
from src.core.logging import get_logger
from src.db.models import TicketCategory

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClassificationOutput:
    category: TicketCategory
    confidence: float
    confidence_level: str
    is_multi_domain: bool
    top2_gap: float
    classification_method: str
    all_probabilities: dict[str, float]


class TicketClassifier:
    def __init__(self, trained: TrainedClassifier) -> None:
        self._trained = trained

    def _predict_sync(self, text: str) -> dict[TicketCategory, float]:
        proba = self._trained.pipeline.predict_proba([text])[0]
        return {
            TicketCategory(cls): float(prob)
            for cls, prob in zip(self._trained.pipeline.classes_, proba, strict=False)
        }

    async def classify(self, title: str, description: str) -> ClassificationOutput:
        text = f"{title} {description}"
        class_probs: dict[TicketCategory, float] = await asyncio.to_thread(
            self._predict_sync, text
        )

        result: ConfidenceResult = score(class_probs)

        logger.debug(
            "ticket_classified",
            category=result.top_category.value,
            confidence=round(result.confidence, 4),
            level=result.confidence_level,
            multi_domain=result.is_multi_domain,
        )

        return ClassificationOutput(
            category=result.top_category,
            confidence=result.confidence,
            confidence_level=result.confidence_level,
            is_multi_domain=result.is_multi_domain,
            top2_gap=result.top2_gap,
            classification_method="tfidf_svm_calibrated",
            all_probabilities={cat.value: prob for cat, prob in class_probs.items()},
        )


def build_classifier(model_path: Path) -> TicketClassifier:
    trained = load_trained(model_path)
    return TicketClassifier(trained=trained)
