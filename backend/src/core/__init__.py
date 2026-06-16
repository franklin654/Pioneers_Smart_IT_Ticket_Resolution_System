"""Core: typed settings, structured logging, domain exception hierarchy."""

from src.core.config import Settings, get_settings
from src.core.exceptions import (
    AppBaseException,
    ClassificationError,
    ConflictError,
    DuplicateTicketError,
    ForbiddenError,
    LLMUnavailableError,
    NotFoundError,
    PIIMaskingError,
    RAGRetrievalError,
    RateLimitExceededError,
    ResolutionNotFoundError,
    TicketNotFoundError,
    UnauthorizedError,
    ValidationError,
)
from src.core.logging import configure_logging, get_logger

__all__ = [
    "AppBaseException",
    "ClassificationError",
    "ConflictError",
    "DuplicateTicketError",
    "ForbiddenError",
    "LLMUnavailableError",
    "NotFoundError",
    "PIIMaskingError",
    "RAGRetrievalError",
    "RateLimitExceededError",
    "ResolutionNotFoundError",
    "Settings",
    "TicketNotFoundError",
    "UnauthorizedError",
    "ValidationError",
    "configure_logging",
    "get_logger",
    "get_settings",
]
