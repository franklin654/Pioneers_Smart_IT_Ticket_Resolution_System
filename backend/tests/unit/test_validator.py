"""Unit tests for TicketValidator (src/ingestion/validator.py).

All tests operate on plain Python objects — no database, no network calls.
The validator is instantiated fresh for each test class to avoid shared state.
"""

import pytest

from src.core.exceptions import ValidationError
from src.db.models import TicketCategory, TicketSource
from src.ingestion.pipeline import IngestionContext
from src.ingestion.validator import TicketValidator


def _make_ctx(
    title: str = "Server is down and not responding to pings",
    description: str = "The production server has stopped responding to health checks since 09:00 UTC.",
    priority: int = 2,
    category_hint: TicketCategory | None = None,
) -> IngestionContext:
    """Build a minimal IngestionContext for testing."""
    return IngestionContext(
        raw_title=title,
        raw_description=description,
        priority=priority,
        category_hint=category_hint,
        source=TicketSource.API,
    )


# ── Happy path ────────────────────────────────────────────────────────────────


class TestValidatorHappyPath:
    def setup_method(self):
        self.validator = TicketValidator()

    def test_valid_ticket_populates_clean_fields(self):
        ctx = _make_ctx()
        result = self.validator.validate(ctx)
        assert result.clean_title is not None
        assert result.clean_description is not None

    def test_clean_title_matches_sanitized_input(self):
        ctx = _make_ctx(title="VPN is down")
        result = self.validator.validate(ctx)
        assert result.clean_title == "VPN is down"

    def test_clean_description_matches_sanitized_input(self):
        ctx = _make_ctx(description="User cannot connect to the VPN from home network.")
        result = self.validator.validate(ctx)
        assert result.clean_description == "User cannot connect to the VPN from home network."

    @pytest.mark.parametrize("priority", [1, 2, 3, 4, 5])
    def test_all_valid_priorities_accepted(self, priority):
        ctx = _make_ctx(priority=priority)
        result = self.validator.validate(ctx)
        assert result.clean_title is not None  # no exception raised

    def test_category_hint_not_validated_by_validator(self):
        """Category hint validation happens at Pydantic schema layer, not here."""
        ctx = _make_ctx(category_hint=TicketCategory.SECURITY)
        result = self.validator.validate(ctx)
        assert result.clean_title is not None

    def test_category_hint_none_accepted(self):
        ctx = _make_ctx(category_hint=None)
        result = self.validator.validate(ctx)
        assert result.clean_title is not None


# ── Sanitization ──────────────────────────────────────────────────────────────


class TestSanitization:
    def setup_method(self):
        self.validator = TicketValidator()

    def test_leading_whitespace_stripped_from_title(self):
        ctx = _make_ctx(title="   VPN Down")
        result = self.validator.validate(ctx)
        assert result.clean_title == "VPN Down"

    def test_trailing_whitespace_stripped_from_title(self):
        ctx = _make_ctx(title="VPN Down   ")
        result = self.validator.validate(ctx)
        assert result.clean_title == "VPN Down"

    def test_internal_whitespace_collapsed_in_title(self):
        ctx = _make_ctx(title="VPN   is   Down")
        result = self.validator.validate(ctx)
        assert result.clean_title == "VPN is Down"

    def test_internal_whitespace_collapsed_in_description(self):
        ctx = _make_ctx(description="The server  has  stopped   responding to requests.")
        result = self.validator.validate(ctx)
        assert "  " not in result.clean_description

    def test_html_tag_stripped_from_title(self):
        ctx = _make_ctx(title="<b>VPN is down</b>")
        result = self.validator.validate(ctx)
        assert "<b>" not in result.clean_title
        assert "VPN is down" in result.clean_title

    def test_html_tag_stripped_from_description(self):
        ctx = _make_ctx(description="User gets <b>error 403</b> when accessing the portal.")
        result = self.validator.validate(ctx)
        assert "<b>" not in result.clean_description
        assert "error 403" in result.clean_description

    def test_html_with_attributes_stripped(self):
        ctx = _make_ctx(title='<span style="color:red">Alert</span>')
        result = self.validator.validate(ctx)
        assert "<span" not in result.clean_title
        assert "Alert" in result.clean_title

    def test_script_tag_stripped_text_preserved(self):
        ctx = _make_ctx(
            description="<script>alert(1)</script>The database is unresponsive since morning."
        )
        result = self.validator.validate(ctx)
        assert "<script>" not in result.clean_description
        assert "The database is unresponsive" in result.clean_description

    def test_null_bytes_stripped(self):
        ctx = _make_ctx(title="VPN\x00Down")
        result = self.validator.validate(ctx)
        assert "\x00" not in result.clean_title

    def test_unicode_content_preserved(self):
        unicode_title = "サーバーがダウンしています"  # Japanese: "The server is down"
        ctx = _make_ctx(title=unicode_title)
        result = self.validator.validate(ctx)
        assert result.clean_title == unicode_title

    def test_arabic_content_preserved(self):
        arabic_desc = "الخادم لا يستجيب للطلبات الواردة من الشبكة الداخلية."
        ctx = _make_ctx(description=arabic_desc)
        result = self.validator.validate(ctx)
        assert arabic_desc in result.clean_description


# ── Validation failures ───────────────────────────────────────────────────────


class TestValidationFailures:
    def setup_method(self):
        self.validator = TicketValidator()

    def test_title_too_short_raises(self):
        ctx = _make_ctx(title="ab")
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "title"

    def test_title_too_long_raises(self):
        ctx = _make_ctx(title="x" * 201)
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "title"

    def test_title_exactly_at_min_length_accepted(self):
        ctx = _make_ctx(title="abc")  # exactly 3 chars
        result = self.validator.validate(ctx)
        assert result.clean_title == "abc"

    def test_title_exactly_at_max_length_accepted(self):
        ctx = _make_ctx(title="x" * 200)
        result = self.validator.validate(ctx)
        assert len(result.clean_title) == 200

    def test_description_too_short_raises(self):
        ctx = _make_ctx(description="Too short")  # 9 chars
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "description"

    def test_description_exactly_at_min_length_accepted(self):
        ctx = _make_ctx(description="x" * 10)  # exactly 10 chars
        result = self.validator.validate(ctx)
        assert len(result.clean_description) == 10

    def test_description_too_long_raises(self):
        ctx = _make_ctx(description="x" * 5001)
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "description"

    def test_priority_zero_raises(self):
        ctx = _make_ctx(priority=0)
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "priority"

    def test_priority_six_raises(self):
        ctx = _make_ctx(priority=6)
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "priority"

    def test_priority_negative_raises(self):
        ctx = _make_ctx(priority=-1)
        with pytest.raises(ValidationError):
            self.validator.validate(ctx)

    def test_priority_bool_raises(self):
        # bool is a subclass of int in Python; True == 1, but we reject booleans
        ctx = _make_ctx(priority=True)  # type: ignore[arg-type]
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "priority"


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def setup_method(self):
        self.validator = TicketValidator()

    def test_title_becomes_too_short_after_html_strip_raises(self):
        """<b>ab</b> → "ab" (2 chars) which is below TITLE_MIN=3."""
        ctx = _make_ctx(title="<b>ab</b>")
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "title"

    def test_description_only_whitespace_raises(self):
        ctx = _make_ctx(description="          ")
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "description"

    def test_description_only_html_tags_raises(self):
        """Tags stripped → empty string → below min length."""
        ctx = _make_ctx(description="<div><p></p></div>")
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        assert exc_info.value.detail["field"] == "description"

    def test_mixed_html_and_technical_content_preserved(self):
        ctx = _make_ctx(
            description="<b>ERROR</b>: Database connection pool exhausted after 30 retries."
        )
        result = self.validator.validate(ctx)
        assert "ERROR" in result.clean_description
        assert "Database connection pool" in result.clean_description

    def test_validation_error_is_serializable(self):
        """ValidationError.to_dict() must be JSON-serializable."""
        import json
        ctx = _make_ctx(title="x")
        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(ctx)
        # Should not raise
        json.dumps(exc_info.value.to_dict())

    def test_strip_html_static_method_directly(self):
        assert TicketValidator._strip_html("<b>hello</b>") == "hello"
        assert TicketValidator._strip_html("no tags here") == "no tags here"
        assert TicketValidator._strip_html("<img src='x' onerror='alert(1)'>") == ""

    def test_sanitize_text_static_method_directly(self):
        assert TicketValidator._sanitize_text("  hello   world  ") == "hello world"
        assert TicketValidator._sanitize_text("<b>hi</b>") == "hi"
        assert TicketValidator._sanitize_text("a\x00b") == "ab"
