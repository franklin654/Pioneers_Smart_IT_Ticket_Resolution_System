import pytest

from src.db.models import TicketSource, TicketStatus
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.ticket_repo import TicketRepository


def _vec(value: float, dim: int = 384) -> list[float]:
    return [value] * dim


@pytest.mark.asyncio
async def test_create_and_get_by_ticket_id(db_session) -> None:
    ticket_repo = TicketRepository(db_session)
    embedding_repo = EmbeddingRepository(db_session)

    ticket = await ticket_repo.create(
        title="t",
        description="d",
        original_description="d",
        category=None,
        priority=3,
        status=TicketStatus.NEW,
        source=TicketSource.API,
        pii_detected=False,
        content_hash="b" * 64,
    )
    await embedding_repo.create(
        ticket_id=ticket.id, embedding=_vec(0.1), model_version="all-MiniLM-L6-v2"
    )

    fetched = await embedding_repo.get_by_ticket_id(ticket.id)
    assert fetched is not None
    assert fetched.model_version == "all-MiniLM-L6-v2"
    assert len(fetched.embedding) == 384


@pytest.mark.asyncio
async def test_get_by_ticket_id_returns_none_when_absent(db_session) -> None:
    import uuid

    embedding_repo = EmbeddingRepository(db_session)
    assert await embedding_repo.get_by_ticket_id(uuid.uuid4()) is None
