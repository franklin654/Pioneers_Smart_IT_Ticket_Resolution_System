"""Unit tests for PIIMasker (src/ingestion/pii_masker.py).

Presidio loads the en_core_web_lg spaCy model on first use (~2–3 seconds).
Tests in this module are marked ``slow`` so they can be excluded from fast
CI runs with ``pytest -m "not slow"``.

Run the full suite (with Presidio) using:
    pytest tests/unit/test_pii_masker.py -v

Run only fast (non-Presidio) tests using:
    pytest tests/unit/test_pii_masker.py -v -m "not slow"
"""

import pytest

from src.db.models import TicketSource
from src.ingestion.pipeline import IngestionContext
from src.ingestion.pii_masker import PIIMasker


def _make_ctx(description: str, clean_title: str = "Server issue") -> IngestionContext:
    """Build a minimal context with clean_description set."""
    ctx = IngestionContext(
        raw_title=clean_title,
        raw_description=description,
        priority=2,
        category_hint=None,
        source=TicketSource.API,
    )
    ctx.clean_title = clean_title
    ctx.clean_description = description
    return ctx


# ── Resilience tests (fast — no Presidio) ─────────────────────────────────────


class TestPIIMaskerResilience:
    """Fast tests that do not invoke Presidio — verify fallback behaviour."""

    def test_empty_description_returns_empty(self):
        masker = PIIMasker()
        ctx = _make_ctx(description="")
        ctx.clean_description = ""
        result = masker.mask(ctx)
        assert result.masked_description == ""
        assert result.pii_detected is False

    def test_none_clean_description_handled(self):
        masker = PIIMasker()
        ctx = _make_ctx(description="")
        ctx.clean_description = None  # type: ignore[assignment]
        result = masker.mask(ctx)
        assert result.masked_description == ""

    def test_masker_does_not_raise_on_presidio_failure(self, monkeypatch):
        """If Presidio raises, the masker falls back to original text."""
        masker = PIIMasker()

        def _bad_analyzer():
            raise RuntimeError("Presidio exploded")

        monkeypatch.setattr(masker, "_get_analyzer", _bad_analyzer)

        ctx = _make_ctx(description="User john.doe@company.com reported an issue.")
        result = masker.mask(ctx)

        # Must not raise; falls back to original text
        assert result.masked_description == ctx.clean_description
        assert result.pii_detected is False
        assert result.pii_entity_types == []

    def test_pii_entity_types_empty_when_no_pii(self, monkeypatch):
        """When Presidio returns no results, pii_entity_types is empty list."""
        masker = PIIMasker()

        # Stub analyzer to return no results
        class _FakeAnalyzer:
            def analyze(self, **kwargs):
                return []

        class _FakeAnonymizer:
            def anonymize(self, **kwargs):
                class R:
                    text = kwargs["text"]
                return R()

        monkeypatch.setattr(masker, "_get_analyzer", lambda: _FakeAnalyzer())
        monkeypatch.setattr(masker, "_get_anonymizer", lambda: _FakeAnonymizer())

        ctx = _make_ctx(description="The application server crashed at boot.")
        result = masker.mask(ctx)
        assert result.pii_detected is False
        assert result.pii_entity_types == []

    def test_pii_detected_true_when_results_found(self, monkeypatch):
        """When Presidio finds results, pii_detected is True."""
        from unittest.mock import MagicMock

        masker = PIIMasker()

        mock_result = MagicMock()
        mock_result.entity_type = "EMAIL_ADDRESS"
        mock_result.start = 5
        mock_result.end = 25

        class _FakeAnalyzer:
            def analyze(self, **kwargs):
                return [mock_result]

        class _FakeAnonymizedResult:
            text = "User <EMAIL_ADDRESS> reported an issue."

        class _FakeAnonymizer:
            def anonymize(self, **kwargs):
                return _FakeAnonymizedResult()

        monkeypatch.setattr(masker, "_get_analyzer", lambda: _FakeAnalyzer())
        monkeypatch.setattr(masker, "_get_anonymizer", lambda: _FakeAnonymizer())

        ctx = _make_ctx(description="User test@example.com reported an issue.")
        result = masker.mask(ctx)

        assert result.pii_detected is True
        assert "EMAIL_ADDRESS" in result.pii_entity_types
        assert "<EMAIL_ADDRESS>" in result.masked_description

    def test_lazy_init_analyzer_is_none_before_mask(self):
        masker = PIIMasker()
        assert masker._analyzer is None

    def test_lazy_init_anonymizer_is_none_before_mask(self):
        masker = PIIMasker()
        assert masker._anonymizer is None

    def test_supported_entities_count(self):
        assert len(PIIMasker.SUPPORTED_ENTITIES) == 8

    def test_supported_entities_contains_expected_types(self):
        expected = {
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN",
            "CREDIT_CARD", "IP_ADDRESS", "DATE_TIME", "LOCATION",
        }
        assert expected == set(PIIMasker.SUPPORTED_ENTITIES)


# ── Integration-style tests (slow — requires Presidio + spaCy model) ──────────


@pytest.mark.slow
class TestPIIMaskerWithPresidio:
    """Tests that invoke the real Presidio engine.

    Marked as ``slow`` because loading the spaCy model takes ~2–3 seconds.
    Shared masker instance across the class to load the model only once.
    """

    @pytest.fixture(scope="class")
    def masker(self):
        return PIIMasker()

    def test_plain_technical_text_unchanged(self, masker):
        # Deliberately exclude timestamps/dates — Presidio's DATE_TIME detector
        # flags expressions like "09:15 UTC", which is correct behaviour but
        # would make this assertion fail. Technical terms alone are not PII.
        ctx = _make_ctx(
            description="The database connection pool exhausted all available connections and rejected new requests."
        )
        result = masker.mask(ctx)
        assert result.pii_detected is False
        assert result.masked_description == ctx.clean_description

    def test_email_address_masked(self, masker):
        ctx = _make_ctx(
            description="User john.doe@example.com reported that the VPN client crashes on startup."
        )
        result = masker.mask(ctx)
        assert "john.doe@example.com" not in result.masked_description
        assert result.pii_detected is True
        assert "EMAIL_ADDRESS" in result.pii_entity_types

    def test_ip_address_masked(self, masker):
        ctx = _make_ctx(
            description="Unauthorized login attempt from 192.168.100.50 was detected in the audit log."
        )
        result = masker.mask(ctx)
        assert "192.168.100.50" not in result.masked_description
        assert result.pii_detected is True

    def test_phone_number_masked_indian_international(self, masker):
        # Indian international format (+91 XXXXXXXXXX) — reliably detected
        ctx = _make_ctx(
            description="Call +91 9876543210 to escalate this critical infrastructure outage."
        )
        result = masker.mask(ctx)
        assert "9876543210" not in result.masked_description
        assert result.pii_detected is True

    def test_phone_number_masked_indian_with_leading_zero(self, masker):
        # Indian domestic format with leading 0 (09XXXXXXXXX)
        ctx = _make_ctx(
            description="The on-call engineer can be reached at 09876543210 for P1 incidents."
        )
        result = masker.mask(ctx)
        assert "09876543210" not in result.masked_description
        assert result.pii_detected is True

    def test_phone_number_masked_indian_10_digit(self, masker):
        # Plain 10-digit Indian mobile (9XXXXXXXXX)
        ctx = _make_ctx(
            description="Contact the SRE team lead at 9123456789 for emergency access requests."
        )
        result = masker.mask(ctx)
        assert "9123456789" not in result.masked_description
        assert result.pii_detected is True

    def test_technical_content_preserved_alongside_pii(self, masker):
        ctx = _make_ctx(
            description=(
                "User john.doe@example.com reports ERROR 500 on the payment-service pod "
                "running Kubernetes v1.28 in the us-east-1 cluster."
            )
        )
        result = masker.mask(ctx)
        assert "ERROR 500" in result.masked_description
        assert "payment-service" in result.masked_description
        assert "Kubernetes" in result.masked_description
        assert "john.doe@example.com" not in result.masked_description

    def test_multiple_pii_entities_all_masked(self, masker):
        ctx = _make_ctx(
            description=(
                "john.doe@example.com called from 555-987-6543 to report a security incident."
            )
        )
        result = masker.mask(ctx)
        assert "john.doe@example.com" not in result.masked_description
        assert "555-987-6543" not in result.masked_description
        assert result.pii_detected is True

    def test_masked_text_uses_entity_type_tags(self, masker):
        ctx = _make_ctx(
            description="Send logs to admin@corp.example.com for further analysis."
        )
        result = masker.mask(ctx)
        assert "<EMAIL_ADDRESS>" in result.masked_description

    def test_result_is_string_not_none(self, masker):
        ctx = _make_ctx(description="The application server is failing health checks.")
        result = masker.mask(ctx)
        assert isinstance(result.masked_description, str)
