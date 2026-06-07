"""End-to-end classifier training CLI script.

Loads labeled tickets from the database, generates embeddings, trains a
Logistic Regression model, evaluates on a held-out test set, and saves
the serialized artifact to ``data/models/classifier.pkl``.

Usage::

    python -m scripts.train_classifier
    python -m scripts.train_classifier --test-size 0.15 --c 2.0
    python -m scripts.train_classifier --model-output data/models/v2.pkl

Prerequisites:
    - Database initialized (``python -m scripts.setup_db``)
    - Kaggle data loaded (``python -m scripts.load_kaggle_data``)
    - ``data/models/`` directory (created automatically if missing)
"""

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from src.classification.trainer import ClassifierTrainer, TrainingConfig
from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.database import AsyncSessionLocal, init_db
from src.db.repositories.ticket_repo import TicketRepository
from src.embedding.generator import EmbeddingGenerator

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    test_size: float = typer.Option(0.20, "--test-size", help="Fraction held out for evaluation"),
    c: float = typer.Option(1.0, "--c", help="Logistic Regression regularization strength"),
    max_iter: int = typer.Option(1000, "--max-iter", help="Maximum solver iterations"),
    model_output: Path = typer.Option(
        Path("data/models/classifier.pkl"),
        "--model-output",
        help="Output path for the serialized model artifact",
    ),
) -> None:
    """Train the IT ticket classifier and save the model artifact."""
    asyncio.run(_train(test_size=test_size, c=c, max_iter=max_iter, model_output=model_output))


async def _train(
    test_size: float,
    c: float,
    max_iter: int,
    model_output: Path,
) -> None:
    settings = get_settings()
    await init_db()

    console.print("\n[bold cyan]IT Ticket Classifier — Training[/bold cyan]\n")

    # ── Load model & data ──────────────────────────────────────────────────
    console.print("Loading embedding model...")
    embedding_gen = EmbeddingGenerator(settings)

    config = TrainingConfig(
        C=c,
        max_iter=max_iter,
        test_size=test_size,
        model_output_path=model_output,
    )

    async with AsyncSessionLocal() as session:
        ticket_repo = TicketRepository(session)
        trainer = ClassifierTrainer(
            embedding_generator=embedding_gen,
            ticket_repo=ticket_repo,
            settings=settings,
            config=config,
        )

        try:
            result = await trainer.train()
        except Exception as exc:
            console.print(f"[bold red]Training failed:[/bold red] {exc}")
            sys.exit(1)

    # ── Print results ──────────────────────────────────────────────────────
    console.print("\n[bold green]── Training Results ─────────────────────────[/bold green]")
    console.print(f"  Accuracy:       [bold]{result.accuracy:.4f}[/bold]")
    console.print(f"  Macro F1:       [bold]{result.macro_f1:.4f}[/bold]")
    console.print(f"  Train samples:  {result.training_samples:,}")
    console.print(f"  Test samples:   {result.test_samples:,}")
    console.print(f"  Model version:  {result.model_version}")

    table = Table(title="\nPer-Category F1 Scores", show_header=True)
    table.add_column("Category", style="cyan")
    table.add_column("F1 Score", justify="right")
    table.add_column("Status", justify="center")

    for cat, f1 in sorted(result.per_class_f1.items()):
        status = "✅" if f1 >= 0.90 else "⚠️"
        table.add_row(cat, f"{f1:.4f}", status)

    console.print(table)

    f1_status = "✅ PASS" if result.macro_f1 >= 0.90 else "❌ BELOW TARGET (need ≥ 0.90)"
    console.print(f"\nOverall F1 gate:  [bold]{f1_status}[/bold]")
    console.print(f"Model saved to:   [bold]{result.model_path}[/bold]\n")

    if result.macro_f1 < 0.90:
        sys.exit(1)


if __name__ == "__main__":
    app()
