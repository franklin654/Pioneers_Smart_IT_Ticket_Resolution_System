"""Batch-classify all WEBHOOK tickets that lack a classification record.

Loads the trained classifier and processes all ServiceNow test-set tickets
(source=WEBHOOK) that have not yet been classified, creating Classification
rows so the routing_accuracy_eval can compare predicted vs ground-truth.

Usage::

    python -m scripts.batch_classify_webhook
    python -m scripts.batch_classify_webhook --limit 500
"""

import asyncio

import typer
from rich.console import Console
from rich.progress import track

from src.classification.classifier import TicketClassifier
from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.database import AsyncSessionLocal, init_db
from src.db.models import Classification, ConfidenceLevel, TicketSource, TicketStatus
from src.db.repositories.ticket_repo import TicketRepository

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    limit: int = typer.Option(1000, "--limit", help="Max WEBHOOK tickets to process"),
) -> None:
    """Classify all unclassified WEBHOOK tickets and persist results."""
    asyncio.run(_run(limit=limit))


async def _run(limit: int) -> None:
    settings = get_settings()
    await init_db()

    console.print("\n[bold cyan]Batch Classify — WEBHOOK Test Set[/bold cyan]\n")

    classifier = TicketClassifier.from_settings(settings)
    console.print(f"  Classifier loaded from: [dim]{settings.model_dir}[/dim]")

    async with AsyncSessionLocal() as session:
        repo = TicketRepository(session)
        tickets = await repo.get_by_source(TicketSource.WEBHOOK, limit=limit)

    unclassified = [t for t in tickets if t.classification is None]
    console.print(f"  WEBHOOK tickets:    {len(tickets)}")
    console.print(f"  Already classified: {len(tickets) - len(unclassified)}")
    console.print(f"  To classify:        {len(unclassified)}\n")

    if not unclassified:
        console.print("[green]All WEBHOOK tickets already classified.[/green]")
        return

    classified = 0
    errors = 0

    for ticket in track(unclassified, description="Classifying..."):
        try:
            text = f"{ticket.title} {ticket.description}"
            output = classifier.predict(text)

            async with AsyncSessionLocal() as session:
                classification = Classification(
                    ticket_id=ticket.id,
                    predicted_category=output.predicted_category,
                    confidence=output.confidence,
                    confidence_level=output.confidence_level,
                    top_categories=output.top_categories,
                    is_multi_domain=output.is_multi_domain,
                    classification_method=output.classification_method,
                )
                session.add(classification)
                await session.commit()

            classified += 1
        except Exception as exc:
            logger.warning(f"Failed to classify ticket {ticket.id}: {exc}")
            errors += 1

    console.print(f"\n  Classified: [green]{classified}[/green]")
    if errors:
        console.print(f"  Errors:     [red]{errors}[/red]")
    console.print("\n[green]Done — run routing_accuracy_eval to evaluate.[/green]\n")


if __name__ == "__main__":
    app()
