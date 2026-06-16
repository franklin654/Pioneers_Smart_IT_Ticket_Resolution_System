"""Generate and persist embeddings for all knowledge_base_entries.

Run once after `load_tickets.py` to populate the vector column used by the
dense retrieval leg of the RAG pipeline.

Usage:
    python scripts/embed_knowledge_base.py
    python scripts/embed_knowledge_base.py --batch-size 64
"""

from __future__ import annotations

import argparse
import asyncio

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.database import session_scope
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.embedding.generator import EmbeddingGenerator

logger = get_logger(__name__)

_COMMIT_EVERY = 200


async def embed_all(batch_size: int) -> None:
    settings = get_settings()
    generator = EmbeddingGenerator(
        model_name=settings.embedding_model,
        batch_size=batch_size,
    )

    async with session_scope() as session:
        repo = KnowledgeBaseRepository(session)
        entries = await repo.get_all_for_bm25()

    needs_embed = [e for e in entries if e.embedding is None]
    logger.info("embed_kb_start", total=len(entries), needs_embed=len(needs_embed))

    if not needs_embed:
        logger.info("embed_kb_already_complete")
        return

    texts = [f"{e.title} {e.description}" for e in needs_embed]
    vectors: list[list[float]] = await generator.encode(texts)

    async with session_scope() as session:
        repo = KnowledgeBaseRepository(session)
        for i, (entry, vector) in enumerate(zip(needs_embed, vectors, strict=False), start=1):
            await repo.set_embedding(entry.id, vector)
            if i % _COMMIT_EVERY == 0:
                await session.commit()
                logger.info("embed_kb_progress", done=i, total=len(needs_embed))
        await session.commit()

    logger.info("embed_kb_complete", embedded=len(needs_embed))


def main() -> None:
    configure_logging()
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=settings.embedding_batch_size)
    args = parser.parse_args()
    asyncio.run(embed_all(args.batch_size))


if __name__ == "__main__":
    main()
