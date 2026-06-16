import uuid
from unittest.mock import AsyncMock

import pytest

from src.core.exceptions import DuplicateTicketError
from src.ingestion.deduplicator import Deduplicator, compute_content_hash


def test_compute_content_hash_is_case_and_whitespace_insensitive() -> None:
    assert compute_content_hash("  Title  ", "Some Description") == compute_content_hash(
        "title", "some description"
    )


def test_compute_content_hash_differs_for_different_content() -> None:
    assert compute_content_hash("a", "b") != compute_content_hash("a", "c")


@pytest.mark.asyncio
async def test_check_raises_on_exact_duplicate() -> None:
    existing_id = uuid.uuid4()
    ticket_repo = AsyncMock()
    ticket_repo.get_by_content_hash.return_value = type("Existing", (), {"id": existing_id})()
    embedding_repo = AsyncMock()
    dedup = Deduplicator(ticket_repo, embedding_repo, similarity_threshold=0.95)

    with pytest.raises(DuplicateTicketError) as exc_info:
        await dedup.check("Title", "Description")

    assert exc_info.value.details == [
        {"existing_ticket_id": str(existing_id), "duplicate_type": "exact"}
    ]
    embedding_repo.find_near_duplicate.assert_not_called()


@pytest.mark.asyncio
async def test_check_skips_near_dup_check_when_no_embedding_generator() -> None:
    ticket_repo = AsyncMock()
    ticket_repo.get_by_content_hash.return_value = None
    embedding_repo = AsyncMock()
    dedup = Deduplicator(ticket_repo, embedding_repo, similarity_threshold=0.95)

    result = await dedup.check("Title", "Description")

    assert result.content_hash == compute_content_hash("Title", "Description")
    embedding_repo.find_near_duplicate.assert_not_called()


@pytest.mark.asyncio
async def test_check_raises_on_near_duplicate_when_generator_present() -> None:
    near_dup_id = uuid.uuid4()
    ticket_repo = AsyncMock()
    ticket_repo.get_by_content_hash.return_value = None
    embedding_repo = AsyncMock()
    embedding_repo.find_near_duplicate.return_value = near_dup_id
    generator = type("Generator", (), {"encode_single": staticmethod(lambda text: [0.1] * 384)})()
    dedup = Deduplicator(
        ticket_repo, embedding_repo, similarity_threshold=0.95, embedding_generator=generator
    )

    with pytest.raises(DuplicateTicketError) as exc_info:
        await dedup.check("Title", "Description")

    assert exc_info.value.details[0]["duplicate_type"] == "near"
    assert exc_info.value.details[0]["existing_ticket_id"] == str(near_dup_id)


@pytest.mark.asyncio
async def test_check_returns_hash_when_generator_present_but_no_near_dup_found() -> None:
    ticket_repo = AsyncMock()
    ticket_repo.get_by_content_hash.return_value = None
    embedding_repo = AsyncMock()
    embedding_repo.find_near_duplicate.return_value = None
    generator = type("Generator", (), {"encode_single": staticmethod(lambda text: [0.1] * 384)})()
    dedup = Deduplicator(
        ticket_repo, embedding_repo, similarity_threshold=0.95, embedding_generator=generator
    )

    result = await dedup.check("Title", "Description")

    assert result.content_hash == compute_content_hash("Title", "Description")
