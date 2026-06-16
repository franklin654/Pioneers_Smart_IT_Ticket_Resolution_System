"""Unit tests for RAG components: knowledge_base, generator (parse), reranker (MMR)."""

from __future__ import annotations

import json

import pytest

from src.db.models import ResolutionStep


# ---------------------------------------------------------------------------
# knowledge_base: KnowledgeBaseIndex.build + .search
# ---------------------------------------------------------------------------


class _MockEntry:
    """Minimal stand-in for KnowledgeBaseEntry in unit tests."""

    def __init__(self, id_: str, title: str, description: str, category: object) -> None:
        self.id = id_
        self.title = title
        self.description = description
        self.category = category
        self.resolution = "Step 1: do something."
        self.embedding = None


def test_bm25_index_build_and_search() -> None:
    from src.db.models import TicketCategory
    from src.rag.knowledge_base import KnowledgeBaseIndex

    entries = [
        _MockEntry("1", "Database replication lag", "Postgres replica is behind master.", TicketCategory.DATABASE),
        _MockEntry("2", "VPN connectivity issue", "User cannot connect to VPN.", TicketCategory.NETWORK),
        _MockEntry("3", "Disk space full on /var", "Server out of disk space.", TicketCategory.INFRASTRUCTURE),
    ]
    index = KnowledgeBaseIndex.build(entries)  # type: ignore[arg-type]

    results = index.search("database replication latency", top_k=3)

    assert len(results) >= 1
    top_entry, top_score = results[0]
    assert top_entry.title == "Database replication lag"
    assert top_score > 0


def test_bm25_category_filter() -> None:
    from src.db.models import TicketCategory
    from src.rag.knowledge_base import KnowledgeBaseIndex

    entries = [
        _MockEntry("1", "database slow queries", "Queries taking 10s+", TicketCategory.DATABASE),
        _MockEntry("2", "network timeout", "Packets dropped on switch.", TicketCategory.NETWORK),
        _MockEntry("3", "database backup failed", "pg_dump exited with error.", TicketCategory.DATABASE),
    ]
    index = KnowledgeBaseIndex.build(entries)  # type: ignore[arg-type]

    results = index.search("database issue", top_k=5, category_filter=TicketCategory.DATABASE)

    assert all(e.category == TicketCategory.DATABASE for e, _ in results)
    assert len(results) == 2


def test_bm25_empty_corpus_raises() -> None:
    from src.rag.knowledge_base import KnowledgeBaseIndex

    with pytest.raises(ValueError, match="empty corpus"):
        KnowledgeBaseIndex.build([])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# generator: _parse_steps
# ---------------------------------------------------------------------------


def test_parse_steps_valid_json_array() -> None:
    from src.rag.generator import _parse_steps

    raw = json.dumps([
        {"step_number": 1, "instruction": "Check disk usage"},
        {"step_number": 2, "instruction": "Clear old logs"},
    ])
    steps = _parse_steps(raw)

    assert len(steps) == 2
    assert isinstance(steps[0], ResolutionStep)
    assert steps[0].step_number == 1
    assert steps[1].instruction == "Clear old logs"


def test_parse_steps_strips_markdown_fence() -> None:
    from src.rag.generator import _parse_steps

    raw = '```json\n[{"step_number": 1, "instruction": "Run diagnostics"}]\n```'
    steps = _parse_steps(raw)

    assert len(steps) == 1
    assert steps[0].step_number == 1


def test_parse_steps_raises_on_no_array() -> None:
    import json as _json

    from src.rag.generator import _parse_steps

    with pytest.raises(_json.JSONDecodeError):
        _parse_steps("This is just text, no JSON array here.")


def test_parse_steps_skips_invalid_items_but_keeps_valid() -> None:
    from src.rag.generator import _parse_steps

    raw = json.dumps([
        {"step_number": 1, "instruction": "Valid step"},
        {"bad_field": "no step_number or instruction"},
        {"step_number": 2, "instruction": "Another valid step"},
    ])
    steps = _parse_steps(raw)
    assert len(steps) == 2
