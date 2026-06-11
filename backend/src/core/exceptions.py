"""Custom exception hierarchy for the ticket routing application.

All application exceptions inherit from ``AppBaseException`` which carries
a human-readable ``message``, an HTTP ``status_code``, a machine-readable
``error_code``, and an optional ``detail`` dict for structured context.

Usage::

    raise TicketNotFoundError("abc-123")
    raise DuplicateTicketError(existing_ticket_id="abc-123", duplicate_type="exact")
    raise LLMUnavailableError(backend="ollama", reason="connection refused")
"""

from typing import Any


class AppBaseException(Exception):
    """Root exception for all application-defined errors.

    Args:
        message: Human-readable error description.
        detail: Optional dict with structured context (e.g. IDs, field names).
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.detail = detail or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSON API error responses."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "detail": self.detail,
        }


# ── 4xx Client errors ─────────────────────────────────────────────────────────

class ValidationError(AppBaseException):
    """Input failed schema or business-rule validation (HTTP 400)."""

    status_code = 400
    error_code = "VALIDATION_ERROR"


class AuthenticationError(AppBaseException):
    """Missing or invalid authentication credentials (HTTP 401)."""

    status_code = 401
    error_code = "AUTHENTICATION_ERROR"


class AuthorizationError(AppBaseException):
    """Authenticated user lacks required permissions (HTTP 403)."""

    status_code = 403
    error_code = "AUTHORIZATION_ERROR"


class TicketNotFoundError(AppBaseException):
    """Requested ticket does not exist (HTTP 404).

    Args:
        ticket_id: The ID that was looked up and not found.
    """

    status_code = 404
    error_code = "TICKET_NOT_FOUND"

    def __init__(self, ticket_id: str) -> None:
        super().__init__(
            message=f"Ticket '{ticket_id}' not found",
            detail={"ticket_id": ticket_id},
        )


class DuplicateTicketError(AppBaseException):
    """Incoming ticket is a duplicate of an existing one (HTTP 409).

    Args:
        existing_ticket_id: ID of the ticket already in the system.
        duplicate_type: ``"exact"`` (hash match) or ``"near"`` (embedding similarity).
    """

    status_code = 409
    error_code = "DUPLICATE_TICKET"

    def __init__(self, existing_ticket_id: str, duplicate_type: str) -> None:
        super().__init__(
            message=f"Ticket is a {duplicate_type} duplicate of '{existing_ticket_id}'",
            detail={
                "existing_ticket_id": existing_ticket_id,
                "duplicate_type": duplicate_type,
            },
        )


class RateLimitError(AppBaseException):
    """Client has exceeded the allowed request rate (HTTP 429).

    Args:
        retry_after: Seconds until the rate limit window resets.
    """

    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            message="Rate limit exceeded. Try again later.",
            detail={"retry_after_seconds": retry_after},
        )


# ── 5xx Server errors ─────────────────────────────────────────────────────────

class ClassificationError(AppBaseException):
    """Classifier failed to produce a result (HTTP 500)."""

    status_code = 500
    error_code = "CLASSIFICATION_ERROR"


class EmbeddingError(AppBaseException):
    """Embedding model failed to encode input (HTTP 500)."""

    status_code = 500
    error_code = "EMBEDDING_ERROR"


class RAGRetrievalError(AppBaseException):
    """RAG retrieval pipeline encountered an error (HTTP 500)."""

    status_code = 500
    error_code = "RAG_RETRIEVAL_ERROR"


class KnowledgeBaseError(AppBaseException):
    """Knowledge base operation failed (HTTP 500)."""

    status_code = 500
    error_code = "KNOWLEDGE_BASE_ERROR"


class LLMUnavailableError(AppBaseException):
    """LLM backend is unreachable or returned an error (HTTP 503).

    Args:
        backend: Which backend was attempted (``"ollama"`` or ``"claude"``).
        reason: Short description of the failure.
    """

    status_code = 503
    error_code = "LLM_UNAVAILABLE"

    def __init__(self, backend: str, reason: str) -> None:
        super().__init__(
            message=f"LLM backend '{backend}' is unavailable: {reason}",
            detail={"backend": backend, "reason": reason},
        )
