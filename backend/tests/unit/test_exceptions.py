"""Unit tests for the custom exception hierarchy (src/core/exceptions.py)."""

import pytest

from src.core.exceptions import (
    AppBaseException,
    AuthenticationError,
    AuthorizationError,
    ClassificationError,
    DuplicateTicketError,
    EmbeddingError,
    KnowledgeBaseError,
    LLMUnavailableError,
    RAGRetrievalError,
    RateLimitError,
    TicketNotFoundError,
    ValidationError,
)


class TestAppBaseException:
    def test_to_dict_contains_required_keys(self):
        exc = AppBaseException("Something broke")
        d = exc.to_dict()
        assert "error_code" in d
        assert "message" in d
        assert "detail" in d

    def test_to_dict_with_detail(self):
        exc = AppBaseException("broken", detail={"key": "value"})
        assert exc.to_dict()["detail"] == {"key": "value"}

    def test_default_detail_is_empty_dict(self):
        exc = AppBaseException("broken")
        assert exc.detail == {}

    def test_message_set_on_instance(self):
        exc = AppBaseException("test message")
        assert exc.message == "test message"

    def test_str_representation(self):
        exc = AppBaseException("test message")
        assert str(exc) == "test message"

    def test_to_dict_is_json_serializable(self):
        import json
        exc = AppBaseException("broken", detail={"id": "123"})
        # Should not raise
        json.dumps(exc.to_dict())


class TestClientErrors:
    @pytest.mark.parametrize(
        "ExcClass, expected_status, expected_code",
        [
            (ValidationError, 400, "VALIDATION_ERROR"),
            (AuthenticationError, 401, "AUTHENTICATION_ERROR"),
            (AuthorizationError, 403, "AUTHORIZATION_ERROR"),
            (RateLimitError, 429, "RATE_LIMIT_EXCEEDED"),
        ],
    )
    def test_status_and_error_code(self, ExcClass, expected_status, expected_code):
        if ExcClass is RateLimitError:
            exc = ExcClass(retry_after=60)
        else:
            exc = ExcClass("test")
        assert exc.status_code == expected_status
        assert exc.error_code == expected_code


class TestTicketNotFoundError:
    def test_status_code(self):
        assert TicketNotFoundError("abc").status_code == 404

    def test_error_code(self):
        assert TicketNotFoundError("abc").error_code == "TICKET_NOT_FOUND"

    def test_ticket_id_in_detail(self):
        exc = TicketNotFoundError("abc-123")
        assert exc.detail["ticket_id"] == "abc-123"

    def test_ticket_id_in_message(self):
        exc = TicketNotFoundError("abc-123")
        assert "abc-123" in exc.message


class TestDuplicateTicketError:
    def test_status_code(self):
        assert DuplicateTicketError("id", "exact").status_code == 409

    def test_error_code(self):
        assert DuplicateTicketError("id", "exact").error_code == "DUPLICATE_TICKET"

    def test_detail_contains_existing_id(self):
        exc = DuplicateTicketError("existing-id", "exact")
        assert exc.detail["existing_ticket_id"] == "existing-id"

    def test_detail_contains_duplicate_type(self):
        exc = DuplicateTicketError("existing-id", "near")
        assert exc.detail["duplicate_type"] == "near"

    @pytest.mark.parametrize("dup_type", ["exact", "near"])
    def test_both_duplicate_types(self, dup_type):
        exc = DuplicateTicketError("some-id", dup_type)
        assert exc.detail["duplicate_type"] == dup_type


class TestLLMUnavailableError:
    def test_status_code(self):
        assert LLMUnavailableError("ollama", "conn refused").status_code == 503

    def test_error_code(self):
        assert LLMUnavailableError("ollama", "timeout").error_code == "LLM_UNAVAILABLE"

    def test_detail_contains_backend(self):
        exc = LLMUnavailableError(backend="claude", reason="api error")
        assert exc.detail["backend"] == "claude"

    def test_detail_contains_reason(self):
        exc = LLMUnavailableError(backend="ollama", reason="connection refused")
        assert exc.detail["reason"] == "connection refused"

    def test_backend_in_message(self):
        exc = LLMUnavailableError(backend="ollama", reason="timeout")
        assert "ollama" in exc.message


class TestRateLimitError:
    def test_retry_after_in_detail(self):
        exc = RateLimitError(retry_after=30)
        assert exc.detail["retry_after_seconds"] == 30

    def test_status_code(self):
        assert RateLimitError(retry_after=60).status_code == 429


class TestServerErrors:
    @pytest.mark.parametrize(
        "ExcClass, expected_status, expected_code",
        [
            (ClassificationError, 500, "CLASSIFICATION_ERROR"),
            (EmbeddingError, 500, "EMBEDDING_ERROR"),
            (RAGRetrievalError, 500, "RAG_RETRIEVAL_ERROR"),
            (KnowledgeBaseError, 500, "KNOWLEDGE_BASE_ERROR"),
        ],
    )
    def test_status_and_error_code(self, ExcClass, expected_status, expected_code):
        exc = ExcClass("test error")
        assert exc.status_code == expected_status
        assert exc.error_code == expected_code

    def test_all_server_errors_are_app_base_exception(self):
        for ExcClass in [ClassificationError, EmbeddingError, RAGRetrievalError, KnowledgeBaseError]:
            assert issubclass(ExcClass, AppBaseException)
