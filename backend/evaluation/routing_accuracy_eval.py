"""Routing accuracy evaluation using the synthetic held-out test set.

Queries all tickets ingested via the held-out test set loader
(``source = WEBHOOK``) that have been processed through the pipeline,
then compares the classifier's ``predicted_category`` against the ground-truth
``ticket.category`` (populated at load time from the synthetic test CSV).

Metrics:
    - **Overall accuracy** — fraction of classified test tickets where
      ``predicted_category == ticket.category``.
    - **Per-category accuracy** — accuracy broken down across all 6 categories.
    - **Coverage** — fraction of test tickets that were actually classified
      (i.e. reached the classifier step).

Usage::

    python -m evaluation.routing_accuracy_eval
    python -m evaluation.routing_accuracy_eval --fail-under 0.75

Exit codes:
    0 — accuracy >= threshold
    1 — accuracy below threshold OR no classified test tickets found
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import typer
from rich.console import Console
from rich.table import Table

from src.core.logging import get_logger
from src.db.database import AsyncSessionLocal, init_db
from src.db.models import TicketCategory, TicketSource

logger = get_logger(__name__)
console = Console()
app = typer.Typer(add_completion=False)

_DEFAULT_FAIL_UNDER = 0.75
_TEST_SOURCE = TicketSource.WEBHOOK


@dataclass
class RoutingAccuracyResult:
    test_set_size: int
    classified_count: int
    correct_count: int
    accuracy: float
    per_category_correct: Counter = field(default_factory=Counter)
    per_category_total: Counter = field(default_factory=Counter)
    threshold: float = _DEFAULT_FAIL_UNDER
    passed: bool = False


async def _evaluate_and_return(fail_under: float, limit: int = 1000) -> RoutingAccuracyResult:
    """Run evaluation and return a result dataclass (used by run_all.py)."""
    await init_db()

    from src.db.repositories.ticket_repo import TicketRepository

    async with AsyncSessionLocal() as session:
        repo = TicketRepository(session)
        tickets = await repo.get_by_source(_TEST_SOURCE, limit=limit)

    test_set_size = len(tickets)
    classified = [t for t in tickets if t.classification is not None]
    classified_count = len(classified)

    correct_count = 0
    per_category_correct: Counter[str] = Counter()
    per_category_total: Counter[str] = Counter()

    for ticket in classified:
        ground_truth = ticket.category
        predicted = ticket.classification.predicted_category

        if ground_truth is not None:
            cat_key = ground_truth.value
            per_category_total[cat_key] += 1
            if predicted == ground_truth:
                correct_count += 1
                per_category_correct[cat_key] += 1

    denominator = sum(per_category_total.values())
    accuracy = correct_count / denominator if denominator > 0 else 0.0
    passed = accuracy >= fail_under and denominator > 0

    return RoutingAccuracyResult(
        test_set_size=test_set_size,
        classified_count=classified_count,
        correct_count=correct_count,
        accuracy=accuracy,
        per_category_correct=per_category_correct,
        per_category_total=per_category_total,
        threshold=fail_under,
        passed=passed,
    )


async def _evaluate(fail_under: float, limit: int) -> None:
    result = await _evaluate_and_return(fail_under=fail_under, limit=limit)

    console.print("\n[bold cyan]Routing Accuracy Evaluation (Synthetic Test Set)[/bold cyan]\n")
    console.print(f"  Source:           [dim]{_TEST_SOURCE.value}[/dim] (synthetic held-out)")
    console.print(f"  Test set size:    {result.test_set_size}")
    console.print(
        f"  Classified:       {result.classified_count} "
        f"({result.classified_count / result.test_set_size * 100:.1f}%)"
        if result.test_set_size > 0 else "  Classified:       0"
    )

    denominator = sum(result.per_category_total.values())
    console.print(f"  With ground truth:{denominator}")
    console.print(
        f"  Correct routing:  {result.correct_count} / {denominator}"
        if denominator > 0 else "  Correct routing:  N/A"
    )
    console.print(
        f"  Overall accuracy: [bold]{result.accuracy:.3f}[/bold]"
    )

    # ── Per-category table ─────────────────────────────────────────────────
    table = Table(title="\nPer-Category Routing Accuracy", show_header=True)
    table.add_column("Category", style="cyan")
    table.add_column("Correct", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Status", justify="center")

    for cat in TicketCategory:
        total = result.per_category_total.get(cat.value, 0)
        correct = result.per_category_correct.get(cat.value, 0)
        if total == 0:
            acc_str = "—"
            status = "[dim]no samples[/dim]"
        else:
            acc = correct / total
            acc_str = f"{acc:.3f}"
            status = "[bold green]✅[/bold green]" if acc >= fail_under else "[bold red]⚠️[/bold red]"
        table.add_row(cat.value, str(correct), str(total), acc_str, status)

    console.print(table)

    # ── Gate ───────────────────────────────────────────────────────────────
    if denominator == 0:
        console.print(
            "\n[bold red]❌ SKIP — no classified test-set tickets found.[/bold red]"
            "\n  Run the pipeline against the synthetic test set first:"
            "\n  1. python -m scripts.load_tickets --input-path data/raw/synthetic_test.csv --ticket-source webhook"
            "\n  2. python -m scripts.batch_classify_webhook"
        )
        sys.exit(1)

    gate_label = (
        f"[bold green]✅ PASS[/bold green]  {result.accuracy:.3f} >= {fail_under}"
        if result.passed
        else f"[bold red]❌ FAIL[/bold red]  {result.accuracy:.3f} < {fail_under}"
    )
    console.print(f"\nGate (accuracy ≥ {fail_under}): {gate_label}\n")

    if not result.passed:
        sys.exit(1)


@app.command()
def main(
    fail_under: float = typer.Option(
        _DEFAULT_FAIL_UNDER,
        "--fail-under",
        help="Minimum routing accuracy to pass (0–1).",
    ),
    limit: int = typer.Option(
        1000,
        "--limit",
        help="Maximum number of test-set tickets to evaluate.",
    ),
) -> None:
    """Evaluate routing accuracy against the held-out synthetic test set."""
    asyncio.run(_evaluate(fail_under=fail_under, limit=limit))


if __name__ == "__main__":
    app()
