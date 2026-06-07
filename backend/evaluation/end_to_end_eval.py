"""End-to-end pipeline evaluation script.

Measures real-world performance across all tickets that have been fully
processed by the agent pipeline (status: AUTO_RESOLVED, ASSIGNED,
ESCALATED, or CLOSED).

Metrics:
    - **E2E Latency** p50 / p95 / p99 — computed from ``created_at`` to
      ``updated_at`` on each terminal ticket.
    - **Auto-Resolve Rate** — fraction of processed tickets routed to
      AUTO_RESOLVED.
    - **Routing distribution** — counts per RoutingDecision.
    - **Category × routing matrix** — breakdown per ticket category.
    - **Confidence distribution** — HIGH / MEDIUM / LOW counts.
    - **Multi-domain rate** — fraction where the classifier flagged
      multi-domain intent.
    - **Repeated issue rate** — fraction flagged as a repeated issue.

Usage::

    python -m evaluation.end_to_end_eval
    python -m evaluation.end_to_end_eval --fail-latency 5.0 --fail-auto-resolve 25.0

Exit codes:
    0 — all gates pass
    1 — p95 latency exceeds threshold OR auto-resolve rate below threshold
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import typer
from rich.console import Console
from rich.table import Table

from src.core.config import get_settings  # noqa: F401
from src.db.database import AsyncSessionLocal, init_db
from src.db.models import ConfidenceLevel, TicketCategory, TicketStatus
from src.db.repositories.ticket_repo import TicketRepository, TicketSearchFilters

app = typer.Typer(add_completion=False)
console = Console()

_TERMINAL_STATUSES = [
    TicketStatus.AUTO_RESOLVED,
    TicketStatus.ASSIGNED,
    TicketStatus.ESCALATED,
    TicketStatus.CLOSED,
]


@dataclass
class E2EEvalResult:
    """Results of the end-to-end evaluation run.

    Attributes:
        p50_latency: 50th percentile E2E latency in seconds.
        p95_latency: 95th percentile E2E latency in seconds.
        p99_latency: 99th percentile E2E latency in seconds.
        auto_resolve_rate: Percentage of tickets routed to AUTO_RESOLVED.
        total_processed: Total terminal-status tickets evaluated.
        routing_counts: Map of routing_decision → count.
        latency_threshold: Configured p95 gate (seconds).
        auto_resolve_threshold: Configured auto-resolve rate gate (%).
        passed: True when both gates are satisfied.
    """

    p50_latency: float
    p95_latency: float
    p99_latency: float
    auto_resolve_rate: float
    total_processed: int
    routing_counts: Counter = field(default_factory=Counter)
    latency_threshold: float = 5.0
    auto_resolve_threshold: float = 25.0
    passed: bool = False


@app.command()
def main(
    fail_latency: float = typer.Option(
        5.0, "--fail-latency", help="Max allowed p95 E2E latency in seconds"
    ),
    fail_auto_resolve: float = typer.Option(
        25.0, "--fail-auto-resolve", help="Minimum required auto-resolve rate (%)"
    ),
    limit: int = typer.Option(
        2000, "--limit", help="Max tickets to load per terminal status"
    ),
) -> None:
    """Evaluate end-to-end pipeline latency and routing distribution."""
    asyncio.run(_evaluate(fail_latency=fail_latency, fail_auto_resolve=fail_auto_resolve, limit=limit))


async def _evaluate(fail_latency: float, fail_auto_resolve: float, limit: int) -> None:
    await init_db()

    console.print("\n[bold cyan]End-to-End Pipeline Evaluation[/bold cyan]\n")

    # ── Load all terminal-status tickets ───────────────────────────────────
    all_tickets = []
    async with AsyncSessionLocal() as session:
        repo = TicketRepository(session)
        for status in _TERMINAL_STATUSES:
            tickets, _ = await repo.search(
                TicketSearchFilters(status=status), offset=0, limit=limit
            )
            all_tickets.extend(tickets)

    if not all_tickets:
        console.print("[bold red]No processed tickets found.[/bold red]")
        console.print("  Submit and process tickets through the full pipeline first.")
        sys.exit(1)

    console.print(f"  Loaded [bold]{len(all_tickets):,}[/bold] processed tickets\n")

    # ── Latency ────────────────────────────────────────────────────────────
    latencies: list[float] = []
    for ticket in all_tickets:
        if ticket.created_at and ticket.updated_at:
            elapsed = (ticket.updated_at - ticket.created_at).total_seconds()
            if elapsed > 0:
                latencies.append(elapsed)

    latencies.sort()
    n_lat = len(latencies)

    if n_lat >= 2:
        p50 = latencies[int(n_lat * 0.50)]
        p95 = latencies[min(int(n_lat * 0.95), n_lat - 1)]
        p99 = latencies[min(int(n_lat * 0.99), n_lat - 1)]
    elif n_lat == 1:
        p50 = p95 = p99 = latencies[0]
    else:
        p50 = p95 = p99 = 0.0

    lat_table = Table(title="E2E Latency", show_header=True)
    lat_table.add_column("Percentile", style="cyan")
    lat_table.add_column("Latency (s)", justify="right")
    lat_table.add_column("Gate", justify="right")

    lat_table.add_row("p50", f"{p50:.2f}s", "—")
    p95_color = "green" if p95 <= fail_latency else "red"
    lat_table.add_row(
        "p95",
        f"[{p95_color}]{p95:.2f}s[/{p95_color}]",
        f"< {fail_latency:.1f}s",
    )
    lat_table.add_row("p99", f"{p99:.2f}s", "—")
    console.print(lat_table)

    # ── Routing distribution ───────────────────────────────────────────────
    routing_counts: Counter[str] = Counter()
    for ticket in all_tickets:
        if ticket.resolution is not None:
            key = ticket.resolution.routing_decision.value
            routing_counts[key] += 1

    total_routed = sum(routing_counts.values())
    auto_resolve_count = routing_counts.get("auto_resolved", 0)
    auto_resolve_rate  = (auto_resolve_count / total_routed * 100) if total_routed else 0.0

    routing_table = Table(title="\nRouting Distribution", show_header=True)
    routing_table.add_column("Decision", style="cyan")
    routing_table.add_column("Count", justify="right")
    routing_table.add_column("%", justify="right")

    for decision, count in sorted(routing_counts.items()):
        pct   = count / total_routed * 100 if total_routed else 0.0
        color = "green" if decision == "auto_resolved" else "blue" if decision == "assigned" else "red"
        routing_table.add_row(decision, f"[{color}]{count}[/{color}]", f"{pct:.1f}%")

    console.print(routing_table)

    ar_color = "green" if auto_resolve_rate >= fail_auto_resolve else "red"
    console.print(
        f"\nAuto-Resolve Rate: [{ar_color}]{auto_resolve_rate:.1f}%[/{ar_color}]"
        f"  (target ≥ {fail_auto_resolve:.0f}%)"
    )

    # ── Category × routing matrix ──────────────────────────────────────────
    cat_routing: dict[str, Counter[str]] = defaultdict(Counter)
    for ticket in all_tickets:
        if ticket.classification and ticket.resolution:
            cat  = ticket.classification.predicted_category.value
            dec  = ticket.resolution.routing_decision.value
            cat_routing[cat][dec] += 1

    if cat_routing:
        decisions = ["auto_resolved", "assigned", "escalated"]
        cat_table = Table(title="\nCategory × Routing Matrix", show_header=True)
        cat_table.add_column("Category", style="cyan")
        for d in decisions:
            cat_table.add_column(d.replace("_", " ").title(), justify="right")
        cat_table.add_column("Total", justify="right")

        for cat in sorted(cat_routing):
            counts = cat_routing[cat]
            total  = sum(counts.values())
            cat_table.add_row(
                cat,
                *[str(counts.get(d, 0)) for d in decisions],
                str(total),
            )
        console.print(cat_table)

    # ── Confidence + multi-domain + repeated issue stats ───────────────────
    conf_counts: Counter[str] = Counter()
    multi_domain_count = 0
    repeated_count = 0

    for ticket in all_tickets:
        if ticket.classification:
            conf_counts[ticket.classification.confidence_level.value] += 1
            if ticket.classification.is_multi_domain:
                multi_domain_count += 1
        if ticket.resolution and ticket.resolution.is_repeated_issue:
            repeated_count += 1

    total = len(all_tickets)
    stats_table = Table(title="\nAdditional Stats", show_header=True)
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", justify="right")

    for level in [ConfidenceLevel.HIGH, ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM]:
        count = conf_counts.get(level.value, 0)
        stats_table.add_row(
            f"Confidence {level.value.upper()}",
            f"{count} ({count / total * 100:.1f}%)" if total else "0",
        )

    stats_table.add_row(
        "Multi-domain",
        f"{multi_domain_count} ({multi_domain_count / total * 100:.1f}%)" if total else "0",
    )
    stats_table.add_row(
        "Repeated issue",
        f"{repeated_count} ({repeated_count / total * 100:.1f}%)" if total else "0",
    )
    console.print(stats_table)

    # ── Gates ──────────────────────────────────────────────────────────────
    lat_pass = p95 <= fail_latency
    ar_pass  = auto_resolve_rate >= fail_auto_resolve
    passed   = lat_pass and ar_pass

    console.print()
    if not lat_pass:
        console.print(
            f"[bold red]❌ FAIL[/bold red] p95 latency {p95:.2f}s > {fail_latency:.1f}s"
        )
    if not ar_pass:
        console.print(
            f"[bold red]❌ FAIL[/bold red] auto-resolve rate "
            f"{auto_resolve_rate:.1f}% < {fail_auto_resolve:.0f}%"
        )
    if passed:
        console.print(
            f"[bold green]✅ PASS[/bold green] p95 {p95:.2f}s ≤ {fail_latency:.1f}s, "
            f"auto-resolve {auto_resolve_rate:.1f}% ≥ {fail_auto_resolve:.0f}%"
        )
    console.print()

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    app()
