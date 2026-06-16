from src.core.exceptions import (
    AppBaseException,
    ConflictError,
    DuplicateTicketError,
    NotFoundError,
    TicketNotFoundError,
    ValidationError,
)


def test_ticket_not_found_error_shape() -> None:
    err = TicketNotFoundError("abc-123")
    assert err.code == "TICKET_NOT_FOUND"
    assert err.http_status == 404
    assert isinstance(err, NotFoundError)
    assert "abc-123" in err.message


def test_duplicate_ticket_error_is_a_conflict_with_details() -> None:
    err = DuplicateTicketError("existing-id", "near")
    assert err.code == "DUPLICATE_TICKET"
    assert err.http_status == 409
    assert isinstance(err, ConflictError)
    assert err.details == [{"existing_ticket_id": "existing-id", "duplicate_type": "near"}]


def test_validation_error_includes_field_details_when_given() -> None:
    err = ValidationError("Bad value", field="email", issue="must be valid")
    assert err.details == [{"field": "email", "issue": "must be valid"}]


def test_validation_error_without_field_has_no_details() -> None:
    err = ValidationError("Generic failure")
    assert err.details == []


def test_every_domain_exception_is_an_app_base_exception() -> None:
    assert isinstance(TicketNotFoundError("x"), AppBaseException)
    assert isinstance(DuplicateTicketError("x", "exact"), AppBaseException)
