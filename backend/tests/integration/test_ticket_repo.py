from datetime import UTC, datetime, timedelta

import pytest

from src.db.models import TicketCategory, TicketSource, TicketStatus
from src.db.repositories.ticket_repo import TicketRepository, TicketSearchFilters


def _hash(n: int) -> str:
    return f"{n:064x}"


async def _make_ticket(repo: TicketRepository, n: int, **overrides):
    defaults = dict(
        title=f"Ticket {n}",
        description=f"Description {n}",
        original_description=f"Description {n}",
        category=TicketCategory.NETWORK,
        priority=3,
        status=TicketStatus.NEW,
        source=TicketSource.API,
        pii_detected=False,
        content_hash=_hash(n),
    )
    defaults.update(overrides)
    return await repo.create(**defaults)


@pytest.mark.asyncio
async def test_create_and_get_by_id(db_session) -> None:
    repo = TicketRepository(db_session)
    ticket = await _make_ticket(repo, 1, category=TicketCategory.NETWORK)

    fetched = await repo.get_by_id(ticket.id)
    assert fetched is not None
    assert fetched.title == "Ticket 1"
    assert fetched.category == TicketCategory.NETWORK
    assert fetched.status == TicketStatus.NEW


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_unknown_id(db_session) -> None:
    import uuid

    repo = TicketRepository(db_session)
    assert await repo.get_by_id(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_get_with_relations_loads_ticket_without_relations(db_session) -> None:
    repo = TicketRepository(db_session)
    ticket = await _make_ticket(repo, 2)

    fetched = await repo.get_with_relations(ticket.id)
    assert fetched is not None
    assert fetched.classification is None
    assert fetched.resolution is None


@pytest.mark.asyncio
async def test_get_by_content_hash_finds_exact_duplicate(db_session) -> None:
    repo = TicketRepository(db_session)
    ticket = await _make_ticket(repo, 3)

    found = await repo.get_by_content_hash(_hash(3))
    assert found is not None
    assert found.id == ticket.id
    assert await repo.get_by_content_hash(_hash(999)) is None


@pytest.mark.asyncio
async def test_update_status(db_session) -> None:
    repo = TicketRepository(db_session)
    ticket = await _make_ticket(repo, 4, status=TicketStatus.NEW)

    await repo.update_status(ticket.id, TicketStatus.AWAITING_REVIEW)

    fetched = await repo.get_by_id(ticket.id)
    assert fetched is not None
    assert fetched.status == TicketStatus.AWAITING_REVIEW


@pytest.mark.asyncio
async def test_update_category(db_session) -> None:
    repo = TicketRepository(db_session)
    ticket = await _make_ticket(repo, 5, category=None)

    await repo.update_category(ticket.id, TicketCategory.SECURITY)

    fetched = await repo.get_by_id(ticket.id)
    assert fetched is not None
    assert fetched.category == TicketCategory.SECURITY


@pytest.mark.asyncio
async def test_search_filters_by_category_and_status(db_session) -> None:
    repo = TicketRepository(db_session)
    await _make_ticket(repo, 10, category=TicketCategory.SECURITY, status=TicketStatus.NEW)
    await _make_ticket(repo, 11, category=TicketCategory.SECURITY, status=TicketStatus.ESCALATED)
    await _make_ticket(repo, 12, category=TicketCategory.NETWORK, status=TicketStatus.NEW)

    results, total = await repo.search(
        TicketSearchFilters(category=TicketCategory.SECURITY, status=TicketStatus.NEW)
    )

    assert total == 1
    assert len(results) == 1
    assert results[0].content_hash == _hash(10)


@pytest.mark.asyncio
async def test_search_pagination(db_session) -> None:
    repo = TicketRepository(db_session)
    for n in range(20, 25):
        await _make_ticket(repo, n, category=TicketCategory.DATABASE)

    page1, total = await repo.search(
        TicketSearchFilters(category=TicketCategory.DATABASE, offset=0, limit=2)
    )
    page2, _ = await repo.search(
        TicketSearchFilters(category=TicketCategory.DATABASE, offset=2, limit=2)
    )

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert {t.id for t in page1}.isdisjoint({t.id for t in page2})


@pytest.mark.asyncio
async def test_get_training_data_only_returns_categorized_csv_tickets(db_session) -> None:
    repo = TicketRepository(db_session)
    await _make_ticket(repo, 30, source=TicketSource.CSV, category=TicketCategory.APPLICATION)
    await _make_ticket(repo, 31, source=TicketSource.API, category=TicketCategory.APPLICATION)
    await _make_ticket(repo, 32, source=TicketSource.CSV, category=None)

    training_rows = await repo.get_training_data()

    titles = {row[0] for row in training_rows}
    assert "Ticket 30" in titles
    assert "Ticket 31" not in titles  # wrong source
    assert "Ticket 32" not in titles  # no category


@pytest.mark.asyncio
async def test_get_by_source_filters_correctly(db_session) -> None:
    repo = TicketRepository(db_session)
    await _make_ticket(repo, 40, source=TicketSource.WEBHOOK)
    await _make_ticket(repo, 41, source=TicketSource.API)

    webhook_tickets = await repo.get_by_source(TicketSource.WEBHOOK)
    assert {t.content_hash for t in webhook_tickets} == {_hash(40)}


@pytest.mark.asyncio
async def test_count_recent_by_category_excludes_other_sources_and_self(db_session) -> None:
    repo = TicketRepository(db_session)
    live = await _make_ticket(
        repo, 50, category=TicketCategory.INFRASTRUCTURE, source=TicketSource.API
    )
    await _make_ticket(repo, 51, category=TicketCategory.INFRASTRUCTURE, source=TicketSource.API)
    # Bulk-loaded historical data must not count towards "repeated issue" detection.
    await _make_ticket(repo, 52, category=TicketCategory.INFRASTRUCTURE, source=TicketSource.CSV)

    since = datetime.now(UTC) - timedelta(days=30)
    count = await repo.count_recent_by_category(
        TicketCategory.INFRASTRUCTURE, since, exclude_ticket_id=live.id
    )

    assert count == 1  # only ticket 51 — 50 excluded as self, 52 excluded as CSV source
