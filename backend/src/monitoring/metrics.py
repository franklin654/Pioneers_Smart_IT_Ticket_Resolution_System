"""Prometheus metric definitions for TicketIQ.

All metrics use the `ticketiq_` prefix. Call the `record_*` helpers from the
orchestrator after each pipeline completion. Rates and ratios are computed in
Grafana from these raw counters/histograms — no Gauge derivation in-process.

Multiprocess note: if running multiple uvicorn workers, set
`PROMETHEUS_MULTIPROC_DIR` to a shared writable directory and use
`prometheus_client.multiprocess.MultiProcessCollector` in the `/metrics`
handler. For single-worker (default) deployments, the default registry works.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

tickets_processed_total = Counter(
    "ticketiq_tickets_processed_total",
    "Tickets that completed the full pipeline (terminal routing decision).",
    labelnames=["routing_decision", "category"],
)

awaiting_review_total = Counter(
    "ticketiq_awaiting_review_total",
    "Tickets parked at the pre-generation confidence gate (AWAITING_REVIEW). "
    "v2 new status — subset of tickets_processed_total.",
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

ticket_duration_seconds = Histogram(
    "ticketiq_ticket_duration_seconds",
    "Wall-clock seconds spent in each pipeline stage.",
    labelnames=["stage"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

classification_confidence = Histogram(
    "ticketiq_classification_confidence",
    "Classifier top-1 confidence score per ticket.",
    buckets=[0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.0],
)

llm_quality_score = Histogram(
    "ticketiq_llm_quality_score",
    "LLM evaluator quality score (1–5) for tickets that reached generation.",
    buckets=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
)


# ---------------------------------------------------------------------------
# Convenience helpers called from the orchestrator
# ---------------------------------------------------------------------------


def record_pipeline_complete(
    routing_decision: str,
    category: str,
    confidence: float,
    quality_score: float | None,
) -> None:
    """Record a successful full-pipeline run (all stages completed)."""
    tickets_processed_total.labels(
        routing_decision=routing_decision,
        category=category,
    ).inc()
    classification_confidence.observe(confidence)
    if quality_score is not None:
        llm_quality_score.observe(quality_score)


def record_awaiting_review(confidence: float) -> None:
    """Record a ticket parked at the pre-generation gate."""
    awaiting_review_total.inc()
    tickets_processed_total.labels(
        routing_decision="awaiting_review",
        category="unknown",
    ).inc()
    classification_confidence.observe(confidence)
