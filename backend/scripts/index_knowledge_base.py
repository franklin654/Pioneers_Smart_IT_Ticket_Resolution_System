"""Embed all KnowledgeBaseEntry rows that do not yet have a vector.

This script is a prerequisite for Phase 4 (RAG retrieval). Without
embeddings on the knowledge base entries, pgvector similarity search
will return no results.

Usage::

    python -m scripts.index_knowledge_base
    python -m scripts.index_knowledge_base --batch-size 64

Prerequisites:
    - Database initialized and populated (Kaggle data loaded)
    - Embedding model available (downloads automatically on first run)
"""

import asyncio
import sys

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.database import AsyncSessionLocal, init_db
from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
from src.embedding.generator import EmbeddingGenerator

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    batch_size: int = typer.Option(32, "--batch-size", "-b", help="Embedding batch size"),
) -> None:
    """Generate and store embeddings for all unindexed knowledge base entries."""
    asyncio.run(_index(batch_size=batch_size))


async def _index(batch_size: int) -> None:
    settings = get_settings()
    await init_db()

    console.print("\n[bold cyan]Knowledge Base Indexing[/bold cyan]\n")
    console.print("Loading embedding model...")

    try:
        generator = EmbeddingGenerator(settings)
    except Exception as exc:
        console.print(f"[bold red]Failed to load embedding model:[/bold red] {exc}")
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        repo = KnowledgeBaseRepository(session)

        all_entries = await repo.get_all_for_bm25()
        total = len(all_entries)
        unindexed = [e for e in all_entries if e.embedding is None]
        already_indexed = total - len(unindexed)

        console.print(f"  Total KB entries:    {total:,}")
        console.print(f"  Already indexed:     {already_indexed:,}")
        console.print(f"  To index:            {len(unindexed):,}\n")

        if not unindexed:
            console.print("[green]All entries already have embeddings. Nothing to do.[/green]")
            return

        # ── Generate embeddings in batches ────────────────────────────────
        texts = [f"{e.title} {e.description}" for e in unindexed]

        console.print("Generating embeddings...")
        try:
            vectors = generator.encode_batch(texts, batch_size=batch_size, show_progress=True)
        except Exception as exc:
            console.print(f"[bold red]Embedding generation failed:[/bold red] {exc}")
            sys.exit(1)

        # ── Persist in batches of 500 ─────────────────────────────────────
        persisted = 0
        persist_batch = 500

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Storing embeddings...", total=len(unindexed))

            for i in range(0, len(unindexed), persist_batch):
                batch_entries = unindexed[i : i + persist_batch]
                batch_vectors = vectors[i : i + persist_batch]

                for entry, vector in zip(batch_entries, batch_vectors):
                    await repo.update_embedding(entry.id, vector)

                await session.commit()
                persisted += len(batch_entries)
                progress.advance(task, len(batch_entries))

    console.print(
        f"\n[bold green]Done.[/bold green] Indexed {persisted:,} knowledge base entries.\n"
    )


if __name__ == "__main__":
    app()
