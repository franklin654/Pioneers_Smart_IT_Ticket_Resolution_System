"""LLM quality score distribution evaluator.

Analyses the distribution of LLM quality scores stored in the Resolution
table by the EvaluatorAgent.  Scores are on a 0–5 scale (mean of three
dimensions: relevance, completeness, actionability).

Usage::

    python -m evaluation.llm_judge
    python -m evaluation.llm_judge --fail-under 3.5 --limit 2000

Exit codes:
    0 — mean quality score meets the threshold
    1 — mean score below threshold, or no scored resolutions found
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from collections import Counter
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table

from src.core.config import get_settings  # noqa: F401 — ensures settings validated early
from src.db.database import AsyncSessionLocal, init_db
from src.db.models import RoutingDecision
from src.db.repositories.resolution_repo import ResolutionRepository

app = typer.Typer(add_completion=False)
console = Console()


@dataclass
class LLMJudgeResult:
    """Results of the LLM quality score evaluation run.

    Attributes:
        mean_score: Arithmetic mean across all scored resolutions (0–5).
        median_score: Median score.
        std_score: Standard deviation.
        pct_above_threshold: Percentage of scores meeting or exceeding
            ``fail_under`` threshold.
        num_scored: Total resolutions with a quality score.
        threshold: The configured pass/fail threshold.
        passed: True when ``mean_score >= threshold``.
    """

    mean_score: float
    median_score: float
    std_score: float
    pct_above_threshold: float
    num_scored: int
    threshold: float
    passed: bool


@app.command()
def main(
    fail_under: float = typer.Option(
        3.5, "--fail-under", help="Minimum mean quality score (0–5); exits non-zero if not met"
    ),
    limit: int = typer.Option(
        2000, "--limit", help="Maximum resolutions to load"
    ),
) -> None:
    """Evaluate LLM quality score distribution from scored resolutions."""
    asyncio.run(_evaluate(fail_under=fail_under, limit=limit))


async def _evaluate(fail_under: float, limit: int) -> None:
    await init_db()

    console.print("\n[bold cyan]LLM Quality Score Evaluation[/bold cyan]\n")

    async with AsyncSessionLocal() as session:
        repo = ResolutionRepository(session)
        resolutions = await repo.get_all_with_quality_scores(limit=limit)

    if not resolutions:
        console.print("[bold red]No scored resolutions found.[/bold red]")
        console.print("  Process tickets through the full pipeline first.")
        sys.exit(1)

    scores = [r.llm_quality_score for r in resolutions if r.llm_quality_score is not None]
    console.print(f"  Analysing [bold]{len(scores):,}[/bold] scored resolutions\n")

    # ── Summary statistics ─────────────────────────────────────────────────
    mean_score   = statistics.mean(scores)
    median_score = statistics.median(scores)
    std_score    = statistics.stdev(scores) if len(scores) > 1 else 0.0
    pct_above    = sum(1 for s in scores if s >= fail_under) / len(scores) * 100

    console.print(f"[bold]Mean score:[/bold]    {mean_score:.3f} / 5.0")
    console.print(f"[bold]Median score:[/bold]  {median_score:.3f} / 5.0")
    console.print(f"[bold]Std deviation:[/bold] {std_score:.3f}")
    console.print(f"[bold]≥ {fail_under:.1f}:[/bold]          {pct_above:.1f}% of resolutions\n")

    # ── Bucketed distribution ──────────────────────────────────────────────
    buckets = [
        ("4.0 – 5.0", 4.0, 5.0),
        ("3.5 – 4.0", 3.5, 4.0),
        ("3.0 – 3.5", 3.0, 3.5),
        ("2.0 – 3.0", 2.0, 3.0),
        ("0.0 – 2.0", 0.0, 2.0),
    ]
    dist_table = Table(title="Score Distribution", show_header=True)
    dist_table.add_column("Bucket", style="cyan")
    dist_table.add_column("Count", justify="right")
    dist_table.add_column("%", justify="right")

    for label, lo, hi in buckets:
        count = sum(1 for s in scores if lo <= s <= hi)
        pct   = count / len(scores) * 100
        color = "green" if lo >= fail_under else "yellow" if lo >= 3.0 else "red"
        dist_table.add_row(label, f"[{color}]{count}[/{color}]", f"{pct:.1f}%")

    console.print(dist_table)

    # ── Per-routing-decision breakdown ─────────────────────────────────────
    routing_scores: dict[str, list[float]] = {}
    for r in resolutions:
        if r.llm_quality_score is None:
            continue
        key = r.routing_decision.value if isinstance(r.routing_decision, RoutingDecision) else str(r.routing_decision)
        routing_scores.setdefault(key, []).append(r.llm_quality_score)

    if routing_scores:
        routing_table = Table(title="\nMean Score by Routing Decision", show_header=True)
        routing_table.add_column("Routing Decision", style="cyan")
        routing_table.add_column("Count", justify="right")
        routing_table.add_column("Mean Score", justify="right")

        for decision, decision_scores in sorted(routing_scores.items()):
            mean = statistics.mean(decision_scores)
            color = "green" if mean >= fail_under else "yellow" if mean >= 3.0 else "red"
            routing_table.add_row(
                decision,
                str(len(decision_scores)),
                f"[{color}]{mean:.3f}[/{color}]",
            )
        console.print(routing_table)

    # ── CI gate ────────────────────────────────────────────────────────────
    result = LLMJudgeResult(
        mean_score=mean_score,
        median_score=median_score,
        std_score=std_score,
        pct_above_threshold=pct_above,
        num_scored=len(scores),
        threshold=fail_under,
        passed=mean_score >= fail_under,
    )

    gate_text = (
        f"[bold green]✅ PASS[/bold green] (mean {mean_score:.3f} ≥ {fail_under})"
        if result.passed
        else f"[bold red]❌ FAIL[/bold red] (mean {mean_score:.3f} < {fail_under})"
    )
    console.print(f"\nQuality Gate ({fail_under}): {gate_text}\n")

    if not result.passed:
        sys.exit(1)


if __name__ == "__main__":
    app()
