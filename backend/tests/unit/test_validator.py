import pytest

from src.core.exceptions import ValidationError
from src.ingestion.validator import TicketValidator


def test_strips_surrounding_whitespace() -> None:
    result = TicketValidator().validate("  Title  ", "  Description  ")
    assert result.clean_title == "Title"
    assert result.clean_description == "Description"


def test_strips_control_characters_but_keeps_newlines_and_tabs() -> None:
    result = TicketValidator().validate("Title\x00\x07", "Line one\n\tLine two")
    assert result.clean_title == "Title"
    assert result.clean_description == "Line one\n\tLine two"


def test_rejects_whitespace_only_title() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TicketValidator().validate("   ", "A valid description.")
    assert exc_info.value.details == [{"field": "title", "issue": None}]


def test_rejects_title_that_is_only_control_characters() -> None:
    with pytest.raises(ValidationError):
        TicketValidator().validate("\x00\x01\x02", "A valid description.")


def test_rejects_whitespace_only_description() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TicketValidator().validate("A valid title", "   ")
    assert exc_info.value.details == [{"field": "description", "issue": None}]
