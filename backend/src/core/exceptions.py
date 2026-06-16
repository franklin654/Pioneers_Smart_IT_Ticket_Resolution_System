"""Typed domain exception hierarchy.

Every exception here carries a machine-readable `code` and an HTTP status so the
global exception handler (`api/envelope.py`, Phase 6) can convert it to the
standard `{ "error": { "code", "message", "details" } }` envelope without any
per-route try/except. See CLAUDE.md §6 (backend) and `docs/03_BACKEND_DESIGN.md`.

Unexpected exceptions (programming bugs, infrastructure failures) are NOT
caught here — they propagate to the global handler's fallback branch, which
maps them to a generic 500 and logs the full stack trace. Only expected,
typed-domain failures belong in this module.
"""

from __future__ import annotations


class AppBaseException(Exception):
    """Base for every domain exception. Never raised directly."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str, details: list[dict] | None = None) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


class NotFoundError(AppBaseException):
    code = "NOT_FOUND"
    http_status = 404


class TicketNotFoundError(NotFoundError):
    code = "TICKET_NOT_FOUND"

    def __init__(self, ticket_id: object) -> None:
        super().__init__(f"Ticket {ticket_id} was not found.")


class ResolutionNotFoundError(NotFoundError):
    code = "RESOLUTION_NOT_FOUND"

    def __init__(self, ticket_id: object) -> None:
        super().__init__(f"No resolution exists yet for ticket {ticket_id}.")


class ConflictError(AppBaseException):
    """Generic 409 — the request conflicts with the resource's current state.

    New in v2 (see `01_LESSONS_LEARNED.md`): used by `PATCH /tickets/{id}/reclassify`
    when the ticket is not in `AWAITING_REVIEW` status.
    """

    code = "CONFLICT"
    http_status = 409


class DuplicateTicketError(ConflictError):
    code = "DUPLICATE_TICKET"

    def __init__(self, existing_ticket_id: object, duplicate_type: str) -> None:
        super().__init__(
            "A ticket with equivalent content already exists.",
            details=[
                {"existing_ticket_id": str(existing_ticket_id), "duplicate_type": duplicate_type}
            ],
        )


class ValidationError(AppBaseException):
    code = "VALIDATION_ERROR"
    http_status = 422

    def __init__(self, message: str, field: str | None = None, issue: str | None = None) -> None:
        details = [{"field": field, "issue": issue}] if field else []
        super().__init__(message, details=details)


class UnauthorizedError(AppBaseException):
    code = "UNAUTHORIZED"
    http_status = 401


class ForbiddenError(AppBaseException):
    code = "FORBIDDEN"
    http_status = 403


class PIIMaskingError(AppBaseException):
    """Raised when PII masking fails for entity types where masking is mandatory.

    Audit fix L6: v1's masker silently passed through unmasked text on a Presidio
    failure. v2 never ships unmasked PII — this exception halts ingestion instead.
    """

    code = "PII_MASKING_FAILED"
    http_status = 500


class ClassificationError(AppBaseException):
    code = "CLASSIFICATION_ERROR"
    http_status = 500


class RAGRetrievalError(AppBaseException):
    code = "RAG_RETRIEVAL_ERROR"
    http_status = 500


class LLMUnavailableError(AppBaseException):
    code = "LLM_UNAVAILABLE"
    http_status = 503


class RateLimitExceededError(AppBaseException):
    code = "RATE_LIMIT_EXCEEDED"
    http_status = 429
