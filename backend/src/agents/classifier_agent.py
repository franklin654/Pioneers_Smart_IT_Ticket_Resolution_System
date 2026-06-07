"""AutoGen agent wrapping the LinearSVC-backed TicketClassifier.

Receives a CLASSIFY message dict, calls the classifier, persists the
Classification row, updates ticket status, and returns a structured
CLASSIFICATION_RESULT message.

The agent uses ``llm_config=False`` — all intelligence comes from the
pre-trained sklearn model, not an LLM.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import autogen

from src.core.exceptions import ClassificationError
from src.core.logging import get_logger
from src.db.models import Classification, TicketStatus

if TYPE_CHECKING:
    from src.classification.classifier import TicketClassifier
    from src.core.config import Settings
    from src.db.repositories.classification_repo import ClassificationRepository
    from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)


class ClassifierAgent(autogen.ConversableAgent):
    """AutoGen agent that classifies tickets via a trained LinearSVC (calibrated).

    Wraps :class:`~src.classification.classifier.TicketClassifier` and persists
    results to the ``classifications`` table.  Status transitions:
    ``CLASSIFYING → CLASSIFIED`` on success.

    Args:
        classifier: Loaded :class:`TicketClassifier` instance.
        ticket_repo: For updating ticket status.
        classification_repo: For persisting the Classification row.
        settings: Application settings.
    """

    def __init__(
        self,
        classifier: "TicketClassifier",
        ticket_repo: "TicketRepository",
        classification_repo: "ClassificationRepository",
        settings: "Settings",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="ClassifierAgent",
            human_input_mode="NEVER",
            llm_config=False,
            **kwargs,
        )
        self._classifier = classifier
        self._ticket_repo = ticket_repo
        self._classification_repo = classification_repo
        self._settings = settings

    async def _classify(self, msg: dict) -> dict:
        """Run classification and persist results."""
        ticket_id = uuid.UUID(msg["ticket_id"])
        title: str = msg["title"]
        description: str = msg["description"]

        try:
            output = await asyncio.to_thread(self._classifier.predict, f"{title} {description}")
        except ClassificationError as exc:
            logger.error(
                "ClassifierAgent: classification failed",
                extra={"metadata": {"ticket_id": str(ticket_id), "error": str(exc)}},
            )
            return {
                "type": "ERROR",
                "ticket_id": str(ticket_id),
                "error_code": "CLASSIFICATION_ERROR",
                "message": str(exc),
            }

        # Persist Classification row
        classification = Classification(
            ticket_id=ticket_id,
            predicted_category=output.predicted_category,
            confidence=output.confidence,
            confidence_level=output.confidence_level,
            top_categories=output.top_categories,
            is_multi_domain=output.is_multi_domain,
            classification_method=output.classification_method,
        )
        await self._classification_repo.create(classification)

        # Update ticket status
        await self._ticket_repo.update_status(ticket_id, TicketStatus.CLASSIFIED)

        logger.info(
            "ClassifierAgent: ticket classified",
            extra={
                "metadata": {
                    "ticket_id": str(ticket_id),
                    "category": output.predicted_category.value,
                    "confidence": output.confidence,
                    "confidence_level": output.confidence_level.value,
                    "is_multi_domain": output.is_multi_domain,
                }
            },
        )

        return {
            "type": "CLASSIFICATION_RESULT",
            "ticket_id": str(ticket_id),
            "predicted_category": output.predicted_category.value,
            "confidence": output.confidence,
            "confidence_level": output.confidence_level.value,
            "is_multi_domain": output.is_multi_domain,
            "top_categories": output.top_categories,
            "classification_method": output.classification_method,
        }
