"""Two-tier duplicate detection: a SHA-256 exact match on normalized content,
plus an optional embedding-based near-duplicate check.

The near-duplicate check depends on an embedding of the *incoming* ticket,
which needs `embedding/generator.py` — a Phase 3 deliverable that doesn't
exist yet. Rather than import a not-yet-built module, this depends on a
small local `Protocol` so Phase 2 is self-contained; `Deduplicator` runs with
`embedding_generator=None` (exact-match only) until Phase 3's
`build_ingestion_pipeline()` wiring passes a real one in — same disabled-until-
wired shape v1 shipped with (see `docs/01_LESSONS_LEARNED.md`).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Protocol

from src.core.exceptions import DuplicateTicketError
from src.db.repositories.embedding_repo import EmbeddingRepository
from src.db.repositories.ticket_repo import TicketRepository


def compute_content_hash(title: str, description: str) -> str:
    """Canonical hash scheme — must stay identical between the live ingestion
    path and `scripts/load_tickets.py`'s bulk loader, or cross-source
    duplicates (e.g. a CSV-loaded ticket re-submitted live) silently slip
    through. Both call this function rather than each keeping their own copy.
    """
    raw = f"{title.strip().lower()}::{description.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EmbeddingGeneratorProtocol(Protocol):
    def encode_single(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class DedupCheckResult:
    content_hash: str


class Deduplicator:
    def __init__(
        self,
        ticket_repo: TicketRepository,
        embedding_repo: EmbeddingRepository,
        similarity_threshold: float,
        embedding_generator: EmbeddingGeneratorProtocol | None = None,
    ) -> None:
        self._ticket_repo = ticket_repo
        self._embedding_repo = embedding_repo
        self._similarity_threshold = similarity_threshold
        self._embedding_generator = embedding_generator

    async def check(self, title: str, description: str) -> DedupCheckResult:
        content_hash = compute_content_hash(title, description)

        existing = await self._ticket_repo.get_by_content_hash(content_hash)
        if existing is not None:
            raise DuplicateTicketError(existing.id, "exact")

        if self._embedding_generator is not None:
            # CPU-bound (sentence-transformers) — never block the event loop
            # (audit fix H1).
            vector = await asyncio.to_thread(
                self._embedding_generator.encode_single, f"{title} {description}"
            )
            near_dup_id = await self._embedding_repo.find_near_duplicate(
                vector, self._similarity_threshold
            )
            if near_dup_id is not None:
                raise DuplicateTicketError(near_dup_id, "near")

        return DedupCheckResult(content_hash=content_hash)
