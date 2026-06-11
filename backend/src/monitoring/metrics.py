"""Prometheus metric definitions for the TicketIQ backend.

All application metrics are defined here and imported where needed.
Labels use lowercase snake_case values matching enum ``.value`` strings
so Grafana queries are consistent with Python enum values.

Metrics overview:
    HTTP layer:
        http_requests_total              — Counter (method, path, status_code)
        http_request_duration_seconds    — Histogram (method, path)

    Business layer:
        tickets_ingested_total           — Counter (source, category)
        ticket_processing_duration_seconds — Histogram (routing_decision)

    ML layer:
        classification_confidence        — Histogram (category, confidence_level)
        llm_quality_score               — Histogram (routing_decision)
        auto_resolve_rate               — Gauge (rolling, updated per orchestrator run)
"""

from prometheus_client import Counter, Gauge, Histogram

# ── HTTP metrics ───────────────────────────────────────────────────────────────

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests received",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ── Business metrics ───────────────────────────────────────────────────────────

TICKETS_INGESTED_TOTAL = Counter(
    "tickets_ingested_total",
    "Total tickets submitted via the ingest endpoint",
    ["source", "category"],
)

TICKET_PROCESSING_DURATION = Histogram(
    "ticket_processing_duration_seconds",
    "End-to-end processing time from ingestion to terminal status",
    ["routing_decision"],
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0, 60.0],
)

# ── ML metrics ─────────────────────────────────────────────────────────────────

CLASSIFICATION_CONFIDENCE = Histogram(
    "classification_confidence",
    "Classifier confidence score distribution (0–1)",
    ["category", "confidence_level"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0],
)

LLM_QUALITY_SCORE = Histogram(
    "llm_quality_score",
    "LLM evaluator quality score distribution (0–5)",
    ["routing_decision"],
    buckets=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
)

AUTO_RESOLVE_RATE = Gauge(
    "auto_resolve_rate",
    "Rolling auto-resolve rate (0–1) updated after each orchestrator run",
)
