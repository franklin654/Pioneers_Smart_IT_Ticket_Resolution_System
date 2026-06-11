"""Pydantic v2 schemas for classification results."""

from pydantic import BaseModel, ConfigDict

from src.db.models import ConfidenceLevel, TicketCategory


class CategoryProbability(BaseModel):
    """A single category and its predicted probability."""

    category: TicketCategory
    probability: float


class ClassificationResponse(BaseModel):
    """Full classification result returned to API consumers.

    Attributes:
        predicted_category: The top-ranked ticket category.
        confidence: Raw probability for the predicted category (0–1).
        confidence_level: Discretized band: HIGH / MEDIUM / LOW.
        top_categories: Top-3 ``{category, probability}`` pairs.
        is_multi_domain: ``True`` when the top-2 probability difference
            is below the configured threshold, indicating the ticket spans
            multiple domains and should be escalated.
        classification_method: Model identifier used (e.g.
            ``"linearsvc_v20260608_143012"``).
    """

    model_config = ConfigDict(from_attributes=True)

    predicted_category: TicketCategory
    confidence: float
    confidence_level: ConfidenceLevel
    top_categories: list[CategoryProbability]
    is_multi_domain: bool
    classification_method: str
