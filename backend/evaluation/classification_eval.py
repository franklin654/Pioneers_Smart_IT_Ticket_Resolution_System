"""Classification evaluation script.

Loads the trained classifier, runs it against a held-out test set (from
the database or a CSV file), prints a full metrics report, and optionally
enforces a minimum F1 gate for CI pipelines.

Usage::

    python -m evaluation.classification_eval
    python -m evaluation.classification_eval --fail-under 0.90
    python -m evaluation.classification_eval --limit 500

Output:
    - Accuracy, Macro F1, per-class F1 table printed to stdout
    - Confusion matrix PNG saved to ``data/processed/confusion_matrix.png``
    - Exit code 1 if macro F1 < fail_under threshold
"""

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from src.classification.classifier import TicketClassifier
from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.database import AsyncSessionLocal, init_db
from src.db.repositories.ticket_repo import TicketRepository, TicketSearchFilters
from src.db.models import TicketCategory

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    fail_under: float = typer.Option(
        0.90, "--fail-under", help="Minimum macro F1; exits non-zero if not met"
    ),
    per_category: int = typer.Option(
        500, "--per-category", help="Max tickets to sample per category (stratified)"
    ),
) -> None:
    """Evaluate the trained classifier and report metrics."""
    asyncio.run(_evaluate(fail_under=fail_under, per_category=per_category))


async def _evaluate(fail_under: float, per_category: int) -> None:
    settings = get_settings()
    await init_db()

    console.print("\n[bold cyan]Classification Evaluation[/bold cyan]\n")

    # ── Load classifier ────────────────────────────────────────────────────
    console.print("Loading classifier...")
    try:
        classifier = TicketClassifier.from_settings(settings)
    except Exception as exc:
        console.print(f"[bold red]Failed to load classifier:[/bold red] {exc}")
        console.print("  Run: python -m scripts.train_classifier")
        sys.exit(1)

    # ── Load test data — stratified per category ───────────────────────────
    labeled: list = []
    async with AsyncSessionLocal() as session:
        repo = TicketRepository(session)
        for cat in TicketCategory:
            cat_tickets, _ = await repo.search(
                filters=TicketSearchFilters(category=cat),
                offset=0,
                limit=per_category,
            )
            labeled.extend(t for t in cat_tickets if t.category is not None)

    if not labeled:
        console.print("[bold red]No labeled tickets found for evaluation.[/bold red]")
        sys.exit(1)

    console.print(
        f"  Evaluating on {len(labeled):,} labeled tickets "
        f"(up to {per_category} per category)\n"
    )

    # ── Run predictions ────────────────────────────────────────────────────
    y_true: list[str] = []
    y_pred: list[str] = []
    errors = 0

    for ticket in labeled:
        try:
            text = f"{ticket.title} {ticket.description}"
            output = classifier.predict(text)
            y_true.append(ticket.category.value)
            y_pred.append(output.predicted_category.value)
        except Exception as exc:
            logger.warning(f"Prediction failed for ticket {ticket.id}: {exc}")
            errors += 1

    if errors:
        console.print(f"[yellow]Warning: {errors} predictions failed and were skipped.[/yellow]")

    # ── Compute metrics ────────────────────────────────────────────────────
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        confusion_matrix,
    )

    all_labels = [c.value for c in TicketCategory]
    accuracy = accuracy_score(y_true, y_pred)
    report = classification_report(
        y_true,
        y_pred,
        labels=all_labels,
        target_names=all_labels,
        output_dict=True,
        zero_division=0,
    )
    macro_f1: float = report["macro avg"]["f1-score"]
    cm = confusion_matrix(y_true, y_pred, labels=all_labels)

    # ── Print results ──────────────────────────────────────────────────────
    console.print(f"[bold]Accuracy:[/bold]  {accuracy:.4f}")
    console.print(f"[bold]Macro F1:[/bold]  {macro_f1:.4f}")

    table = Table(title="\nPer-Category Metrics", show_header=True)
    table.add_column("Category", style="cyan")
    table.add_column("F1", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    table.add_column("Support", justify="right")

    for cat in all_labels:
        if cat not in report:
            continue
        m = report[cat]
        status_color = "green" if m["f1-score"] >= 0.90 else "yellow"
        table.add_row(
            cat,
            f"[{status_color}]{m['f1-score']:.4f}[/{status_color}]",
            f"{m['precision']:.4f}",
            f"{m['recall']:.4f}",
            str(int(m["support"])),
        )

    console.print(table)

    # ── Save confusion matrix PNG ──────────────────────────────────────────
    _save_confusion_matrix(cm, all_labels)

    # ── CI gate ────────────────────────────────────────────────────────────
    gate_pass = macro_f1 >= fail_under
    status_text = (
        f"[bold green]✅ PASS[/bold green] (macro F1 {macro_f1:.4f} ≥ {fail_under})"
        if gate_pass
        else f"[bold red]❌ FAIL[/bold red] (macro F1 {macro_f1:.4f} < {fail_under})"
    )
    console.print(f"\nF1 Gate ({fail_under}): {status_text}\n")

    if not gate_pass:
        sys.exit(1)


def _save_confusion_matrix(cm, labels: list[str]) -> None:
    """Save a confusion matrix PNG to data/processed/."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend — safe in scripts
        import matplotlib.pyplot as plt
        import numpy as np

        output_path = Path("data/processed/confusion_matrix.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
        plt.colorbar(im, ax=ax)

        tick_marks = np.arange(len(labels))
        short_labels = [lb.replace("_", "\n") for lb in labels]
        ax.set_xticks(tick_marks)
        ax.set_xticklabels(short_labels, rotation=45, ha="right", fontsize=9)
        ax.set_yticks(tick_marks)
        ax.set_yticklabels(short_labels, fontsize=9)
        ax.set_ylabel("True label")
        ax.set_xlabel("Predicted label")
        ax.set_title("Confusion Matrix — IT Ticket Classifier")

        cm_norm = cm.astype("float") / (cm.sum(axis=1, keepdims=True) + 1e-9)
        for i in range(len(labels)):
            for j in range(len(labels)):
                color = "white" if cm_norm[i, j] > 0.5 else "black"
                ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                        color=color, fontsize=8)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()

        console.print(f"Confusion matrix saved to: [dim]{output_path}[/dim]")
    except ImportError:
        console.print("[dim]matplotlib not available — skipping confusion matrix PNG[/dim]")
    except Exception as exc:
        console.print(f"[yellow]Could not save confusion matrix: {exc}[/yellow]")


if __name__ == "__main__":
    app()
