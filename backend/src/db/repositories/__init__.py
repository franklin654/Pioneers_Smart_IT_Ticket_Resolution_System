"""Repository layer — the only modules permitted to issue DB queries."""

from src.db.repositories.base_repo import BaseRepository
from src.db.repositories.classification_repo import ClassificationRepository
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.feedback_repo import FeedbackRepository
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.db.repositories.resolution_repo import ResolutionRepository
from src.db.repositories.ticket_repo import TicketRepository, TicketSearchFilters

__all__ = [
    "BaseRepository",
    "ClassificationRepository",
    "EmbeddingRepository",
    "FeedbackRepository",
    "KnowledgeBaseRepository",
    "ResolutionRepository",
    "TicketRepository",
    "TicketSearchFilters",
]
