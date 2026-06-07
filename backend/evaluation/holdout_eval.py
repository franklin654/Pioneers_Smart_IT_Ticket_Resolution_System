"""Holdout classifier evaluation — runs inference against a CSV, no DB required.

Loads the trained classifier pkl and evaluates it against a CSV file with
ground-truth category labels. Designed for the synthetic test set generated
with ``--mode test``, but works with any CSV that has title/description/category.

Usage::

    python -m evaluation.holdout_eval \\
        --test-csv data/raw/synthetic_test.csv \\
        --fail-under 0.80
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from src.classification.classifier import TicketClassifier
from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)
console = Console()
app = typer.Typer(add_completion=False)


@app.command()
def main(
    test_csv: Path = typer.Option(
        ..., "--test-csv", help="Path to CSV with title, description, category columns"
    ),
    fail_under: float = typer.Option(
        0.80, "--fail-under", help="Overall accuracy gate (exit 1 if below)"
    ),
) -> None:
    """Evaluate the trained classifier against a held-out CSV test set."""
    settings = get_settings()
    classifier = TicketClassifier.from_settings(settings)

    if not test_csv.exists():
        console.print(f"[red]Test CSV not found: {test_csv}[/red]")
        raise typer.Exit(code=1)

    rows = list(csv.DictReader(test_csv.open(encoding="utf-8")))
    if not rows:
        console.print("[red]Test CSV is empty[/red]")
        raise typer.Exit(code=1)

    per_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    correct_total = 0

    for row in rows:
        title = row.get("title", "").strip()
        description = row.get("description", "").strip()
        ground_truth = row.get("category", "").strip().lower()

        if not ground_truth:
            continue

        result = classifier.predict(f"{title} {description}")
        predicted = result.predicted_category.value

        per_cat[ground_truth]["total"] += 1
        if predicted == ground_truth:
            per_cat[ground_truth]["correct"] += 1
            correct_total += 1

    total_evaluated = sum(v["total"] for v in per_cat.values())
    overall_accuracy = correct_total / total_evaluated if total_evaluated else 0.0

    console.print("\n[bold]── Holdout Classifier Evaluation ──[/bold]")
    console.print(f"  Test set size:  {total_evaluated}")
    console.print(f"  Overall accuracy: [bold]{overall_accuracy:.4f}[/bold]\n")

    table = Table(title="Per-Category Accuracy")
    table.add_column("Category", style="cyan")
    table.add_column("Correct", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Status")

    for cat in sorted(per_cat):
        c = per_cat[cat]["correct"]
        t = per_cat[cat]["total"]
        acc = c / t if t else 0.0
        status = "✅" if acc >= fail_under else "⚠️"
        table.add_row(cat, str(c), str(t), f"{acc:.4f}", status)

    console.print(table)

    gate_pass = overall_accuracy >= fail_under
    gate_label = f"[green]✅ PASS[/green]" if gate_pass else f"[red]❌ BELOW TARGET (need ≥ {fail_under})[/red]"
    console.print(f"\n  Overall accuracy gate:  {gate_label}\n")

    logger.info(
        "Holdout evaluation complete",
        extra={"metadata": {"accuracy": overall_accuracy, "total": total_evaluated, "passed": gate_pass}},
    )

    if not gate_pass:
        sys.exit(1)


if __name__ == "__main__":
    app()
