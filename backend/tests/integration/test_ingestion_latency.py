"""Phase 2 gate (docs/07_IMPLEMENTATION_PHASES.md): p50 ingestion latency
< 205ms. Measured without an embedding generator wired in (Phase 3 territory)
— exact-match dedup + PII masking only, which is exactly what ships until
Phase 3's `embedding/generator.py` lands.
"""

from __future__ import annotations

import time

import pytest

from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.ticket_repo import TicketRepository
from src.ingestion.deduplicator import Deduplicator
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.validator import TicketValidator
from src.schemas.ticket import TicketIngestRequest

_P50_BUDGET_SECONDS = 0.205
_SAMPLE_SIZE = 30


@pytest.mark.asyncio
async def test_ingestion_pipeline_p50_latency_is_under_budget(db_session, pii_masker) -> None:
    ticket_repo = TicketRepository(db_session)
    embedding_repo = EmbeddingRepository(db_session)
    pipeline = IngestionPipeline(
        validator=TicketValidator(),
        pii_masker=pii_masker,
        deduplicator=Deduplicator(ticket_repo, embedding_repo, similarity_threshold=0.95),
        ticket_repo=ticket_repo,
    )

    durations: list[float] = []
    for i in range(_SAMPLE_SIZE):
        request = TicketIngestRequest(
            title=f"Latency probe {i}",
            description=f"Plain technical description number {i}, no PII present here at all.",
        )
        start = time.perf_counter()
        await pipeline.run(request)
        durations.append(time.perf_counter() - start)

    durations.sort()
    p50 = durations[len(durations) // 2]
    assert (
        p50 < _P50_BUDGET_SECONDS
    ), f"p50 latency {p50 * 1000:.1f}ms exceeds {_P50_BUDGET_SECONDS * 1000:.0f}ms budget"
