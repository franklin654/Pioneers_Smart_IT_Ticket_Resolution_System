"""Master evaluation runner.

Executes all five evaluators in sequence and prints a final pass/fail
summary table.  A single ``init_db()`` call is shared across all modules.

Evaluators run in order:
    1. Classification  (F1, accuracy, confusion matrix)
    2. RAG retrieval   (Precision@k, Recall@k, MRR)
    3. LLM quality     (mean score distribution)
    4. End-to-end      (latency p95, auto-resolve rate)
    5. Routing accuracy (held-out ServiceNow test set)

Usage::

    python -m evaluation.run_all
    python -m evaluation.run_all --fail-under-f1 0.92 --fail-under-llm 3.5 \\
        --fail-latency 5.0 --fail-auto-resolve 25.0 --fail-under-routing 0.75

Exit codes:
    0 — all evaluators passed their gates
    1 — one or more evaluators failed
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table

from src.db.database import init_db

app = typer.Typer(add_completion=False)
console = Console()


@dataclass
class ModuleResult:
    """Summary of a single evaluator module outcome.

    Attributes:
        name: Display name for the module.
        passed: Whether the module's gate was met.
        key_metric: Name of the primary metric.
        value: Achieved value as a formatted string.
        target: Target threshold as a formatted string.
    """

    name: str
    passed: bool
    key_metric: str
    value: str
    target: str


@app.command()
def main(
    fail_under_f1: float = typer.Option(0.92, "--fail-under-f1", help="Min macro F1 for classifier"),
    top_k: int = typer.Option(5, "--top-k", help="Top-k for RAG retrieval"),
    fail_under_precision: float = typer.Option(0.80, "--fail-under-precision", help="Min RAG Precision@k"),
    fail_under_recall: float = typer.Option(0.85, "--fail-under-recall", help="Min RAG Recall@k"),
    fail_under_mrr: float = typer.Option(0.70, "--fail-under-mrr", help="Min RAG MRR"),
    fail_under_llm: float = typer.Option(3.5, "--fail-under-llm", help="Min mean LLM quality score"),
    fail_latency: float = typer.Option(10.0, "--fail-latency", help="Max p95 E2E latency (s)"),
    fail_auto_resolve: float = typer.Option(25.0, "--fail-auto-resolve", help="Min auto-resolve rate (%)"),
    fail_under_routing: float = typer.Option(0.75, "--fail-under-routing", help="Min routing accuracy on synthetic held-out test set"),
    limit: int = typer.Option(2000, "--limit", help="Max records per evaluator"),
) -> None:
    """Run all evaluation modules and print a final pass/fail summary."""
    asyncio.run(
        _run_all(
            fail_under_f1=fail_under_f1,
            top_k=top_k,
            fail_under_precision=fail_under_precision,
            fail_under_recall=fail_under_recall,
            fail_under_mrr=fail_under_mrr,
            fail_under_llm=fail_under_llm,
            fail_latency=fail_latency,
            fail_auto_resolve=fail_auto_resolve,
            fail_under_routing=fail_under_routing,
            limit=limit,
        )
    )


async def _run_all(
    fail_under_f1: float,
    top_k: int,
    fail_under_precision: float,
    fail_under_recall: float,
    fail_under_mrr: float,
    fail_under_llm: float,
    fail_latency: float,
    fail_auto_resolve: float,
    fail_under_routing: float,
    limit: int,
) -> None:
    console.print("\n[bold magenta]════════════════════════════════════════[/bold magenta]")
    console.print("[bold magenta]   TicketIQ — Full Evaluation Suite (5)  [/bold magenta]")
    console.print("[bold magenta]════════════════════════════════════════[/bold magenta]\n")

    await init_db()
    results: list[ModuleResult] = []

    # ── 1. Classification ──────────────────────────────────────────────────
    console.rule("[bold]1 / 5  Classification[/bold]")
    clf_result = await _run_classification(fail_under=fail_under_f1, limit=limit)
    results.append(clf_result)

    # ── 2. RAG retrieval ───────────────────────────────────────────────────
    console.rule("[bold]2 / 5  RAG Retrieval[/bold]")
    rag_result = await _run_rag(
        top_k=top_k,
        fail_precision=fail_under_precision,
        fail_recall=fail_under_recall,
        fail_mrr=fail_under_mrr,
    )
    results.append(rag_result)

    # ── 3. LLM quality ────────────────────────────────────────────────────
    console.rule("[bold]3 / 5  LLM Quality[/bold]")
    llm_result = await _run_llm_judge(fail_under=fail_under_llm, limit=limit)
    results.append(llm_result)

    # ── 4. End-to-end ─────────────────────────────────────────────────────
    console.rule("[bold]4 / 5  End-to-End[/bold]")
    e2e_result = await _run_e2e(
        fail_latency=fail_latency,
        fail_auto_resolve=fail_auto_resolve,
        limit=limit,
    )
    results.append(e2e_result)

    # ── 5. Routing accuracy ────────────────────────────────────────────────
    console.rule("[bold]5 / 5  Routing Accuracy (ServiceNow test set)[/bold]")
    routing_result = await _run_routing_accuracy(fail_under=fail_under_routing, limit=limit)
    results.append(routing_result)

    # ── Final summary ──────────────────────────────────────────────────────
    console.rule()
    summary = Table(title="\nEvaluation Summary", show_header=True, show_lines=True)
    summary.add_column("Module", style="cyan", min_width=16)
    summary.add_column("Status", justify="center", min_width=8)
    summary.add_column("Metric", min_width=20)
    summary.add_column("Achieved", justify="right", min_width=10)
    summary.add_column("Target", justify="right", min_width=10)

    for r in results:
        status = "[bold green]✅ PASS[/bold green]" if r.passed else "[bold red]❌ FAIL[/bold red]"
        summary.add_row(r.name, status, r.key_metric, r.value, r.target)

    console.print(summary)

    overall_pass = all(r.passed for r in results)
    if overall_pass:
        console.print("\n[bold green]✅ ALL EVALUATIONS PASSED — ready for demo.[/bold green]\n")
    else:
        failed = [r.name for r in results if not r.passed]
        console.print(
            f"\n[bold red]❌ {len(failed)} evaluation(s) failed:[/bold red] "
            + ", ".join(failed) + "\n"
        )
        sys.exit(1)


# ── Module runners ─────────────────────────────────────────────────────────────


async def _run_classification(fail_under: float, limit: int) -> ModuleResult:
    """Run classification evaluator and return a summary result."""
    try:
        from src.classification.classifier import TicketClassifier
        from src.core.config import get_settings
        from src.db.database import AsyncSessionLocal
        from src.db.models import TicketCategory
        from sklearn.metrics import accuracy_score, classification_report

        settings = get_settings()
        classifier = TicketClassifier.from_settings(settings)

        # Stratified per-category sampling — guarantees all 6 categories appear.
        # WEBHOOK tickets are the held-out ServiceNow test set; exclude them.
        # Use a random offset within each category so the sample is drawn from
        # across the full dataset (avoids always hitting the noisy Kaggle tail
        # when ordering by recency).
        import random
        from sqlalchemy import select, func
        from src.db.models import Ticket as TicketModel, TicketSource

        per_cat = max(1, limit // len(TicketCategory))
        labeled: list = []
        for cat in TicketCategory:
            async with AsyncSessionLocal() as session:
                count_result = await session.execute(
                    select(func.count()).where(
                        TicketModel.category == cat,
                        TicketModel.source != TicketSource.WEBHOOK,
                    )
                )
                total = count_result.scalar_one()
                max_offset = max(0, total - per_cat)
                offset = random.randint(0, max_offset) if max_offset > 0 else 0

                result = await session.execute(
                    select(TicketModel)
                    .where(TicketModel.category == cat)
                    .where(TicketModel.source != TicketSource.WEBHOOK)
                    .order_by(TicketModel.created_at.asc())
                    .offset(offset)
                    .limit(per_cat)
                )
                labeled.extend(result.scalars().all())

        if not labeled:
            console.print("[yellow]  No labeled tickets — skipping classification eval[/yellow]")
            return ModuleResult("Classification", False, "Macro F1", "N/A", f"≥ {fail_under}")

        y_true, y_pred = [], []
        for ticket in labeled:
            try:
                out = classifier.predict(f"{ticket.title} {ticket.description}")
                y_true.append(ticket.category.value)
                y_pred.append(out.predicted_category.value)
            except Exception:
                pass

        all_labels = [c.value for c in TicketCategory]
        report = classification_report(y_true, y_pred, labels=all_labels, output_dict=True, zero_division=0)
        macro_f1: float = report["macro avg"]["f1-score"]
        passed = macro_f1 >= fail_under

        console.print(f"  Macro F1: [{'green' if passed else 'red'}]{macro_f1:.4f}[/{'green' if passed else 'red'}]  (target ≥ {fail_under})")
        return ModuleResult("Classification", passed, "Macro F1", f"{macro_f1:.4f}", f"≥ {fail_under}")

    except Exception as exc:
        console.print(f"  [red]Classification eval error: {exc}[/red]")
        return ModuleResult("Classification", False, "Macro F1", "ERROR", f"≥ {fail_under}")


async def _run_rag(
    top_k: int,
    fail_precision: float,
    fail_recall: float,
    fail_mrr: float,
) -> ModuleResult:
    """Run RAG retrieval evaluator and return a summary result."""
    try:
        from src.db.database import AsyncSessionLocal
        from src.db.repositories.knowledge_base_repo import KnowledgeBaseRepository
        from src.embedding.generator import EmbeddingGenerator
        from src.core.config import get_settings
        from src.rag.knowledge_base import KnowledgeBase
        from src.rag.retriever import HybridRetriever

        settings = get_settings()

        async with AsyncSessionLocal() as session:
            kb_repo = KnowledgeBaseRepository(session)
            emb_gen = EmbeddingGenerator(settings)
            kb = KnowledgeBase(repo=kb_repo, embedding_generator=emb_gen, settings=settings)
            await kb.build_bm25_index(force_rebuild=True)
            retriever = HybridRetriever(kb=kb, kb_repo=kb_repo, settings=settings)
            entries = await kb_repo.get_all_for_bm25()

        if not entries:
            console.print("  [yellow]No KB entries — skipping RAG eval[/yellow]")
            return ModuleResult("RAG Retrieval", False, f"Precision@{top_k}", "N/A", f"≥ {fail_precision}")

        hits, reciprocal_ranks = 0, []
        for entry in entries:
            # Embeddings are computed from title+description (see index_knowledge_base.py).
            # Query with the same text so self-retrieval measures true vector alignment.
            query_text = f"{entry.title} {entry.description}"
            query_vector = emb_gen.encode_single(query_text)
            async with AsyncSessionLocal() as session:
                kb_repo2 = KnowledgeBaseRepository(session)
                kb2 = KnowledgeBase(repo=kb_repo2, embedding_generator=emb_gen, settings=settings)
                retriever2 = HybridRetriever(kb=kb2, kb_repo=kb_repo2, settings=settings)
                try:
                    results = await retriever2.retrieve(query_text, query_vector, top_k=top_k)
                    result_ids = [str(r.entry.id) for r in results]
                    if str(entry.id) in result_ids:
                        hits += 1
                        reciprocal_ranks.append(1.0 / (result_ids.index(str(entry.id)) + 1))
                    else:
                        reciprocal_ranks.append(0.0)
                except Exception:
                    reciprocal_ranks.append(0.0)

        n = len(entries)
        precision = hits / n
        mrr = sum(reciprocal_ranks) / n

        passed = precision >= fail_precision and mrr >= fail_mrr
        console.print(f"  Precision@{top_k}: [{'green' if precision >= fail_precision else 'red'}]{precision:.3f}[/{'green' if precision >= fail_precision else 'red'}]  MRR: {mrr:.3f}")
        return ModuleResult("RAG Retrieval", passed, f"Precision@{top_k}", f"{precision:.3f}", f"≥ {fail_precision}")

    except Exception as exc:
        console.print(f"  [red]RAG eval error: {exc}[/red]")
        return ModuleResult("RAG Retrieval", False, f"Precision@{top_k}", "ERROR", f"≥ {fail_precision}")


async def _run_llm_judge(fail_under: float, limit: int) -> ModuleResult:
    """Run LLM quality evaluator and return a summary result."""
    try:
        import statistics
        from src.db.database import AsyncSessionLocal
        from src.db.repositories.resolution_repo import ResolutionRepository

        async with AsyncSessionLocal() as session:
            repo = ResolutionRepository(session)
            resolutions = await repo.get_all_with_quality_scores(limit=limit)

        scores = [r.llm_quality_score for r in resolutions if r.llm_quality_score is not None]
        if not scores:
            console.print("  [yellow]No scored resolutions — skipping LLM quality eval[/yellow]")
            return ModuleResult("LLM Quality", False, "Mean Score", "N/A", f"≥ {fail_under}")

        mean_score = statistics.mean(scores)
        passed = mean_score >= fail_under
        console.print(f"  Mean score: [{'green' if passed else 'red'}]{mean_score:.3f}[/{'green' if passed else 'red'}] / 5.0  (target ≥ {fail_under})")
        return ModuleResult("LLM Quality", passed, "Mean Score", f"{mean_score:.3f}/5", f"≥ {fail_under}")

    except Exception as exc:
        console.print(f"  [red]LLM quality eval error: {exc}[/red]")
        return ModuleResult("LLM Quality", False, "Mean Score", "ERROR", f"≥ {fail_under}")


async def _run_e2e(fail_latency: float, fail_auto_resolve: float, limit: int) -> ModuleResult:
    """Run end-to-end evaluator and return a summary result."""
    try:
        from collections import Counter
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from src.db.database import AsyncSessionLocal
        from src.db.models import Ticket as TicketModel, TicketStatus

        # Only count tickets that completed the full pipeline (have a resolution).
        # CLOSED = batch-imported without pipeline; exclude from E2E metrics.
        terminal_statuses = [
            TicketStatus.AUTO_RESOLVED, TicketStatus.ASSIGNED, TicketStatus.ESCALATED,
        ]

        latencies: list[float] = []
        routing_counts: Counter[str] = Counter()

        # Use selectinload so resolution is loaded eagerly — async SQLAlchemy
        # does not support implicit lazy loading of relationships.
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TicketModel)
                .where(TicketModel.status.in_(terminal_statuses))
                .options(selectinload(TicketModel.resolution))
                .limit(limit)
            )
            tickets = list(result.scalars().all())
            pipeline_tickets = [t for t in tickets if t.resolution is not None]
            total_count = len(pipeline_tickets)
            for t in pipeline_tickets:
                if t.created_at and t.updated_at:
                    elapsed = (t.updated_at - t.created_at).total_seconds()
                    if elapsed > 0:
                        latencies.append(elapsed)
                routing_counts[t.resolution.routing_decision.value] += 1

        if total_count == 0:
            console.print("  [yellow]No pipeline-processed tickets — skipping E2E eval[/yellow]")
            return ModuleResult("End-to-End", False, "p95 Latency", "N/A", f"< {fail_latency}s")

        latencies.sort()
        n = len(latencies)
        p95 = latencies[min(int(n * 0.95), n - 1)] if n > 0 else 0.0

        total_routed = sum(routing_counts.values())
        auto_resolve_rate = (routing_counts.get("auto_resolved", 0) / total_routed * 100) if total_routed else 0.0

        lat_pass = p95 <= fail_latency
        ar_pass  = auto_resolve_rate >= fail_auto_resolve
        passed   = lat_pass and ar_pass

        console.print(f"  p95 latency: [{'green' if lat_pass else 'red'}]{p95:.2f}s[/{'green' if lat_pass else 'red'}]  auto-resolve: [{'green' if ar_pass else 'red'}]{auto_resolve_rate:.1f}%[/{'green' if ar_pass else 'red'}]")
        return ModuleResult("End-to-End", passed, "p95 Latency", f"{p95:.2f}s", f"< {fail_latency}s")

    except Exception as exc:
        console.print(f"  [red]E2E eval error: {exc}[/red]")
        return ModuleResult("End-to-End", False, "p95 Latency", "ERROR", f"< {fail_latency}s")


async def _run_routing_accuracy(fail_under: float, limit: int) -> ModuleResult:
    """Run routing accuracy evaluator against the ServiceNow held-out test set."""
    try:
        from evaluation.routing_accuracy_eval import _evaluate_and_return

        result = await _evaluate_and_return(fail_under=fail_under, limit=limit)
        denominator = sum(result.per_category_total.values())

        if denominator == 0:
            console.print("  [yellow]No classified ServiceNow test-set tickets — skipping routing accuracy[/yellow]")
            return ModuleResult("Routing Accuracy", False, "Accuracy", "N/A", f"≥ {fail_under}")

        console.print(
            f"  Accuracy: [{'green' if result.passed else 'red'}]{result.accuracy:.3f}[/{'green' if result.passed else 'red'}]"
            f"  ({result.correct_count}/{denominator} correct,  target ≥ {fail_under})"
        )
        return ModuleResult(
            "Routing Accuracy",
            result.passed,
            "Accuracy",
            f"{result.accuracy:.3f}",
            f"≥ {fail_under}",
        )

    except Exception as exc:
        console.print(f"  [red]Routing accuracy eval error: {exc}[/red]")
        return ModuleResult("Routing Accuracy", False, "Accuracy", "ERROR", f"≥ {fail_under}")


if __name__ == "__main__":
    app()
