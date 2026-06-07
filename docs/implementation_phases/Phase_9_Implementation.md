# Phase 9 — Docker & Monitoring (Completed)

**Project root:** `app_v2/`
**Status:** Complete — all Python changes syntax-verified, Grafana dashboards provisioned

---

## What Was Built

Phase 9 completes the stack: `docker compose up --build` brings everything online and Prometheus + Grafana monitoring is available immediately with pre-built dashboards.

---

## Files Created / Modified

```text
CREATED:
  backend/src/monitoring/metrics.py              — Prometheus metric definitions (7 metrics)
  backend/src/api/routes/metrics_route.py        — GET /metrics endpoint
  docker/grafana/datasources/prometheus.yml      — Auto-wire Prometheus datasource
  docker/grafana/dashboards/dashboard.yml        — Dashboard provider config
  docker/grafana/dashboards/system_health.json   — HTTP metrics dashboard
  docker/grafana/dashboards/ml_performance.json  — ML metrics dashboard
  docker/grafana/dashboards/business_kpis.json   — Business KPIs dashboard

MODIFIED:
  backend/src/api/middleware/rate_limiter.py     — Exempt /metrics from rate limiting
  backend/src/api/main.py                        — HTTP metrics middleware + metrics router
  backend/src/api/routes/tickets.py              — Record tickets_ingested_total on ingest
  backend/src/api/dependencies.py               — Record ML metrics after orchestration
  docker/docker-compose.yml                     — Health checks for api, frontend, grafana
```

---

## 1. Prometheus Metrics (`src/monitoring/metrics.py`)

Seven metrics defined using `prometheus_client`:

| Metric | Type | Labels | Description |
| --- | --- | --- | --- |
| `http_requests_total` | Counter | method, path, status_code | All HTTP requests |
| `http_request_duration_seconds` | Histogram | method, path | Request latency |
| `tickets_ingested_total` | Counter | source, category | Tickets submitted via API |
| `ticket_processing_duration_seconds` | Histogram | routing_decision | E2E pipeline time |
| `classification_confidence` | Histogram | category, confidence_level | Classifier output distribution |
| `llm_quality_score` | Histogram | routing_decision | LLM evaluator score distribution |
| `auto_resolve_rate` | Gauge | — | Rolling auto-resolve rate (0–1) |

---

## 2. Metrics Endpoint (`src/api/routes/metrics_route.py`)

```text
GET /metrics
```

Returns Prometheus text format. No auth required, exempt from rate limiting. Scraped by Prometheus every 15 seconds (configured in `docker/prometheus.yml`).

---

## 3. HTTP Metrics Middleware (`src/api/main.py`)

Added `@app.middleware("http")` that wraps every request (excluding `/metrics`, `/health/live`, `/health/ready`) and records:

- `http_requests_total` counter (method + path + status_code)
- `http_request_duration_seconds` histogram (method + path)

---

## 4. Rate Limiter Update (`src/api/middleware/rate_limiter.py`)

Changed exemption from single prefix `"/health"` to tuple check:

```python
_EXEMPT_PREFIXES = ("/health", "/metrics")
if any(request.url.path.startswith(p) for p in _EXEMPT_PREFIXES):
```

---

## 5. Business & ML Metrics

**On ingest** (`src/api/routes/tickets.py`): increments `tickets_ingested_total{source="api", category="unknown"}` immediately — category is "unknown" at ingest time since classification is async.

**After orchestration** (`src/api/dependencies.py`): `_record_processing_metrics()` runs after `orchestrator.process_ticket()` completes and records:

- `ticket_processing_duration_seconds` — from `ticket.created_at` to `ticket.updated_at`
- `classification_confidence` — with actual category + confidence_level labels
- `llm_quality_score` — if not None
- `auto_resolve_rate` Gauge — set to 1.0 or 0.0 per ticket

---

## 6. Docker Compose Health Checks

| Service | Health Check Command | Interval | Start Period |
| --- | --- | --- | --- |
| `api` | `curl -f http://localhost:8000/health/ready` | 15s | 30s |
| `frontend` | `curl -sf http://localhost:80/` | 30s | 10s |
| `grafana` | `curl -f http://localhost:3000/api/health` | 15s | 10s |

`frontend` now uses `condition: service_healthy` on `api` (previously just `- api`), ensuring the Angular container doesn't start before the backend is ready.

---

## 7. Grafana Provisioning

Three dashboards are auto-provisioned at startup — no manual configuration needed.

### System Health (`system_health.json`)

- Request rate by path (req/s)
- 5xx error rate (%)
- Response latency p50 / p95 (seconds)
- Requests by status code (bar gauge)

Key queries:

```promql
sum(rate(http_requests_total[1m])) by (path)
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path))
```

### ML Performance (`ml_performance.json`)

- Classification confidence p50/p95 by confidence_level
- LLM quality score p50/p95 by routing_decision
- E2E processing duration p50/p95
- Classifications by category (bar gauge)

Key queries:

```promql
histogram_quantile(0.95, sum(rate(classification_confidence_bucket[5m])) by (le))
histogram_quantile(0.95, sum(rate(ticket_processing_duration_seconds_bucket[5m])) by (le))
```

### Business KPIs (`business_kpis.json`)

- Total tickets ingested (stat)
- Auto-resolve rate % (stat with green/red threshold at 25%)
- Ticket throughput per hour
- Routing distribution (pie chart)
- Tickets over time (time series)

Key queries:

```promql
sum(tickets_ingested_total)
auto_resolve_rate * 100
sum(increase(ticket_processing_duration_seconds_count[1h])) by (routing_decision)
```

---

## 8. Start the Full Stack

```bash
cd app_v2

# Production stack
docker compose -f docker/docker-compose.yml up --build

# Development stack (hot-reload)
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build

# GPU profile (adds Ollama with NVIDIA GPU)
docker compose -f docker/docker-compose.yml --profile gpu up --build
```

---

## 9. Service URLs

| Service | URL | Credentials |
| --- | --- | --- |
| Angular Frontend | <http://localhost:4200> | admin / changeme123 |
| FastAPI Swagger UI | <http://localhost:8000/docs> | — |
| Prometheus Metrics | <http://localhost:8000/metrics> | — |
| Prometheus | <http://localhost:9090> | — |
| Grafana | <http://localhost:3000> | admin / admin |

---

## 10. Verification

```bash
# 1. Check API health
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready

# 2. Verify /metrics endpoint returns Prometheus text
curl http://localhost:8000/metrics | head -30

# 3. Confirm Prometheus scrapes successfully
# Open http://localhost:9090/targets — "ticket_routing_api" should be UP

# 4. Generate some metrics by submitting a ticket
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin&password=changeme123" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -X POST http://localhost:8000/api/v1/tickets/ingest \
     -d '{"title":"VPN auth failure","description":"Cannot connect to corporate VPN from home network since morning.","priority":2}'

# 5. Confirm metric updated
curl -s http://localhost:8000/metrics | grep tickets_ingested_total

# 6. View Grafana dashboards at http://localhost:3000
# Dashboards appear under the "TicketIQ" folder automatically
```

---

## 11. All Phases Complete

| Phase | Status | What |
| --- | --- | --- |
| 1 — Scaffolding | ✅ | DB models, repos, schemas, Docker |
| 2 — Ingestion | ✅ | Validator, PII masker, deduplicator |
| 3 — Classification | ✅ | Embeddings, LinearSVC (calibrated) classifier |
| 4 — RAG | ✅ | Hybrid retriever, MMR reranker, LLM generator |
| 5 — Agents | ✅ | AutoGen orchestrator, 4 agents, routing |
| 6 — API | ✅ | FastAPI REST + WebSocket, JWT auth |
| 7 — Frontend | ✅ | Angular 20 SPA with Material UI |
| 8 — Evaluation | ✅ | 4 evaluators + unified runner |
| 9 — Docker & Monitoring | ✅ | Prometheus metrics, Grafana dashboards, health checks |
