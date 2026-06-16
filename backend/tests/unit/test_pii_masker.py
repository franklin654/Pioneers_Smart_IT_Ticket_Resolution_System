import pytest

from src.ingestion.pii_masker import PIIMasker


# Constructing PIIMasker loads a spaCy model — expensive, so one instance is
# shared across this module's tests rather than rebuilt per test.
@pytest.fixture(scope="module")
def masker() -> PIIMasker:
    return PIIMasker()


@pytest.mark.asyncio
async def test_detects_and_masks_email_and_phone(masker: PIIMasker) -> None:
    result = await masker.mask("Contact me at jane.doe@example.com or 415-555-0199.")

    assert result.pii_detected is True
    assert "EMAIL_ADDRESS" in result.entity_types
    assert "jane.doe@example.com" not in result.masked_text
    assert "415-555-0199" not in result.masked_text


@pytest.mark.asyncio
async def test_detects_ip_address(masker: PIIMasker) -> None:
    result = await masker.mask("The host at 10.0.0.5 stopped responding to pings.")

    assert result.pii_detected is True
    assert "IP_ADDRESS" in result.entity_types
    assert "10.0.0.5" not in result.masked_text


@pytest.mark.asyncio
async def test_plain_technical_text_has_no_false_positive_pii(masker: PIIMasker) -> None:
    result = await masker.mask("The server returned a 500 error during startup.")

    assert result.pii_detected is False
    assert result.entity_types == []
    assert result.masked_text == "The server returned a 500 error during startup."
