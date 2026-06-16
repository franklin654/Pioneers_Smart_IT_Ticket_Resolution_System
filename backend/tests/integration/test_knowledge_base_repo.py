import pytest

from src.db.models import TicketCategory
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository


def _onehot(dim: int, total: int = 384) -> list[float]:
    vec = [0.0] * total
    vec[dim] = 1.0
    return vec


@pytest.mark.asyncio
async def test_search_similar_orders_by_cosine_distance(db_session) -> None:
    repo = KnowledgeBaseRepository(db_session)
    close = await repo.create(
        title="Close match",
        description="d",
        category=TicketCategory.NETWORK,
        resolution="r",
        embedding=_onehot(0),
        source="test",
    )
    far = await repo.create(
        title="Far match",
        description="d",
        category=TicketCategory.NETWORK,
        resolution="r",
        embedding=_onehot(1),
        source="test",
    )

    results = await repo.search_similar(query_vector=_onehot(0), top_k=5)

    assert [entry.id for entry, _ in results][:2] == [close.id, far.id]
    close_distance = next(dist for entry, dist in results if entry.id == close.id)
    far_distance = next(dist for entry, dist in results if entry.id == far.id)
    assert close_distance < far_distance


@pytest.mark.asyncio
async def test_search_similar_respects_category_filter(db_session) -> None:
    repo = KnowledgeBaseRepository(db_session)
    await repo.create(
        title="Network entry",
        description="d",
        category=TicketCategory.NETWORK,
        resolution="r",
        embedding=_onehot(0),
        source="test",
    )
    await repo.create(
        title="Security entry",
        description="d",
        category=TicketCategory.SECURITY,
        resolution="r",
        embedding=_onehot(0),
        source="test",
    )

    results = await repo.search_similar(
        query_vector=_onehot(0), top_k=5, category_filter=TicketCategory.SECURITY
    )

    assert len(results) == 1
    assert results[0][0].category == TicketCategory.SECURITY


@pytest.mark.asyncio
async def test_search_similar_skips_entries_without_an_embedding_yet(db_session) -> None:
    repo = KnowledgeBaseRepository(db_session)
    await repo.create(
        title="Not yet indexed",
        description="d",
        category=TicketCategory.NETWORK,
        resolution="r",
        embedding=None,
        source="test",
    )

    results = await repo.search_similar(query_vector=_onehot(0), top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_get_all_for_bm25_is_bounded(db_session) -> None:
    repo = KnowledgeBaseRepository(db_session)
    for i in range(5):
        await repo.create(
            title=f"Entry {i}",
            description="d",
            category=TicketCategory.APPLICATION,
            resolution="r",
            embedding=None,
            source="test",
        )

    bounded = await repo.get_all_for_bm25(limit=3)
    unbounded = await repo.get_all_for_bm25(limit=50_000)

    assert len(bounded) == 3
    assert len(unbounded) == 5


@pytest.mark.asyncio
async def test_get_by_category(db_session) -> None:
    repo = KnowledgeBaseRepository(db_session)
    await repo.create(
        title="Match",
        description="d",
        category=TicketCategory.DATABASE,
        resolution="r",
        embedding=None,
        source="test",
    )
    await repo.create(
        title="No match",
        description="d",
        category=TicketCategory.NETWORK,
        resolution="r",
        embedding=None,
        source="test",
    )

    results = await repo.get_by_category(TicketCategory.DATABASE)
    assert len(results) == 1
    assert results[0].title == "Match"


@pytest.mark.asyncio
async def test_set_embedding(db_session) -> None:
    repo = KnowledgeBaseRepository(db_session)
    entry = await repo.create(
        title="Needs embedding",
        description="d",
        category=TicketCategory.DATABASE,
        resolution="r",
        embedding=None,
        source="test",
    )

    await repo.set_embedding(entry.id, _onehot(2))

    fetched = await repo.get_by_id(entry.id)
    assert fetched is not None
    assert fetched.embedding is not None
