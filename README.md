# TicketIQ — Smart IT Ticket Resolution System

> **NASSCOM Hackathon · Trail Blazers · v2**
>
> Automated IT support lifecycle: ingest → classify → retrieve → generate → route,
> with confidence-gated human review and live WebSocket status streaming.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Key Features](#key-features)
4. [Project Structure](#project-structure)
5. [Prerequisites](#prerequisites)
6. [Quick Start — Docker (recommended)](#quick-start--docker-recommended)
7. [Local Development Setup](#local-development-setup)
   - [Python environment](#1-python-environment)
   - [PostgreSQL + pgvector](#2-postgresql--pgvector-dev-container)
   - [Environment variables](#3-environment-variables)
   - [Database setup](#4-database-setup)
   - [Generate & load synthetic data](#5-generate--load-synthetic-data)
   - [Embed knowledge base](#6-embed-the-knowledge-base)
   - [Train the classifier](#7-train-the-classifier)
   - [Start the API](#8-start-the-api)
   - [Start the frontend](#9-start-the-frontend)
8. [Running Tests](#running-tests)
9. [Evaluation Suite](#evaluation-suite)
10. [API Reference](#api-reference)
11. [WebSocket](#websocket)
12. [Monitoring](#monitoring)
13. [Environment Variables](#environment-variables)
14. [Architecture Deep-Dive](#architecture-deep-dive)

---

## Overview

IT service companies receive thousands of support tickets daily. Manual triaging
is slow, error-prone, and expensive. TicketIQ automates the full resolution
lifecycle:

| Stage | What happens |
|---|---|
| **Ingest** | Validate input, mask PII with Presidio, deduplicate (SHA-256 exact + embedding near-dup) |
| **Classify** | TF-IDF + LinearSVC + CalibratedClassifierCV across 6 IT domains |
| **Gate** | LOW confidence or multi-domain ambiguity → `AWAITING_REVIEW`; human picks the right category and the pipeline resumes |
| **Retrieve** | Hybrid 40 % dense (pgvector) + 60 % BM25 search over the knowledge base, MMR-reranked |
| **Generate** | Ollama (Mistral-7B) or Claude API produces a structured JSON step array — no free-text markdown |
| **Evaluate** | LLM-as-judge scores Relevance + Completeness + Actionability |
| **Route** | Deterministic rules: HIGH confidence + good quality → `AUTO_RESOLVED`; MEDIUM → `ASSIGNED`; poor quality → `ESCALATED` |

Every decision point exposes a confidence score. The system never silently
auto-resolves when it isn't sure.

### Target Metrics

| Metric | Gate |
|---|---|
| Classification F1 (macro) | ≥ 0.92 |
| RAG Precision@5 | ≥ 0.80 |
| LLM Quality Score (mean) | ≥ 3.5 / 5.0 |
| Auto-Resolve Rate | ≥ 25 % |
| End-to-End Latency p95 | < 5 s |

All gates are enforced by the evaluation suite (`backend/evaluation/`). A build
that does not clear them is not considered done.

---

## Architecture

```
Ticket In
    │
    ▼
[Ingestion]  ← validate · PII mask (Presidio, 8 entity types) · deduplicate
    │
    ▼
[Embedding]  ← sentence-transformers/all-MiniLM-L6-v2  (384-dim, asyncio.to_thread)
    │
    ▼
[Classifier]  ← TF-IDF + LinearSVC + CalibratedClassifierCV
    │
    ▼
[Confidence Scorer]  ← HIGH / MEDIUM / LOW  +  multi-domain detection
    │
    ├── LOW confidence or multi-domain ──────────────────────────────────────┐
    │                                                                         │
    │                                                            [AWAITING_REVIEW]
    │                                                            human picks category
    │                                                            PATCH /tickets/{id}/reclassify
    │                                                                         │
    │                                                            (re-enters as HIGH confidence)
    │                                                                         │
    ▼  HIGH / MEDIUM confidence, not multi-domain ◄──────────────────────────┘
[RAG]
  ├── Dense retrieval  (pgvector cosine, 40 % weight)
  ├── BM25 keyword retrieval          (60 % weight)
  └── MMR reranking  (λ = 0.7)
    │
    ▼
[LLM Generator]  ← Ollama (Mistral-7B) | Claude API
                   Returns structured JSON step array — never free markdown
    │
    ▼
[LLM Evaluator]  ← same LLM backend · quality score 1-5
    │
    ▼
[Router]  ← pure deterministic Python, no LLM
    ├── score ≥ 3.5 · confidence HIGH   → AUTO_RESOLVED
    ├── score ≥ 3.5 · confidence MEDIUM → ASSIGNED
    └── score < 3.5                     → ESCALATED
```

### Technology Stack

| Layer | Technology |
|---|---|
| API | FastAPI (async) + Uvicorn |
| ORM / DB | SQLAlchemy 2.0 (async) + PostgreSQL 16 + pgvector |
| Embedding | sentence-transformers/all-MiniLM-L6-v2 |
| Classifier | scikit-learn LinearSVC + CalibratedClassifierCV |
| Keyword retrieval | rank-bm25 |
| LLM (local) | Ollama + Mistral-7B-Instruct |
| LLM (cloud) | Anthropic Claude API |
| Pipeline agents | AutoGen `ConversableAgent` (called as coroutines — no GroupChat) |
| PII detection | Microsoft Presidio |
| Auth | PyJWT + bcrypt · access token (15 min) + refresh token (HttpOnly cookie) |
| Frontend | React 19 + Vite 8 + TypeScript (strict) + Tailwind CSS v4 |
| Monitoring | Prometheus + Grafana |
| Deployment | Docker Compose |

---

## Key Features

- **Pre-generation confidence gate** — new in v2. Low-confidence and multi-domain
  tickets park at `AWAITING_REVIEW` *before* the expensive RAG + generation
  stages run. A human picks the correct category and the pipeline resumes from
  where it left off. Nothing is wasted.
- **Structured resolution steps** — the LLM is prompted for a JSON array
  (`[{"step_number": N, "instruction": "..."}]`), not free markdown. No
  client-side regex parsing, no sub-bullet-flattening bugs.
- **Hybrid retrieval** — dense (pgvector cosine similarity) + BM25 keyword
  search fused by weighted score, then MMR-reranked for diversity.
- **Live WebSocket status** — `WS /ws/tickets/{id}` streams every status
  transition (including `awaiting_review`) to the browser. No polling.
- **Refresh token rotation** — `/auth/refresh` was a stub in v1; it is fully
  implemented in v2 with single-use rotation.
- **Prometheus metrics + Grafana dashboards** — 5 domain metrics wired into the
  orchestrator; auto-provisioned Grafana dashboard ships with the compose stack.
- **Six-evaluator CI suite** — classification F1, RAG Precision@5, LLM judge,
  end-to-end latency, routing determinism, full holdout pipeline run.

---

## Project Structure

```
.
├── backend/
│   ├── src/
│   │   ├── core/            # config (fails-closed), logging (structlog JSON), exceptions
│   │   ├── db/              # models (6 tables), async session, 6 repositories
│   │   ├── schemas/         # Pydantic v2 request/response schemas
│   │   ├── ingestion/       # validator, pii_masker, deduplicator, pipeline
│   │   ├── embedding/       # EmbeddingGenerator (to_thread), pgvector store
│   │   ├── classification/  # trainer, classifier, confidence scorer
│   │   ├── rag/             # knowledge_base (BM25), retriever (hybrid), reranker (MMR), generator
│   │   ├── agents/          # ClassifierAgent, RAGAgent, EvaluatorAgent, TicketOrchestrator
│   │   ├── routing/         # TicketRouter (5 deterministic rules), EscalationDetector
│   │   ├── api/             # routes, auth middleware, rate limiter, websocket, envelope
│   │   └── monitoring/      # Prometheus metrics (5 counters/histograms)
│   ├── scripts/
│   │   ├── setup_db.py              # idempotent schema provisioning (no Alembic)
│   │   ├── generate_synthetic_data.py  # calls Claude API to create labeled corpus
│   │   ├── load_tickets.py          # loads CSVs into DB (train + held-out sets)
│   │   ├── embed_knowledge_base.py  # embeds KB entries with sentence-transformers
│   │   └── train_classifier.py      # trains + saves LinearSVC model
│   ├── evaluation/
│   │   ├── classification_eval.py   # gate: CV F1 ≥ 0.92
│   │   ├── rag_eval.py              # gate: Precision@5 ≥ 0.80
│   │   ├── llm_judge.py             # gate: mean quality ≥ 3.5 / 5.0
│   │   ├── end_to_end_eval.py       # gate: p95 latency < 5 s
│   │   ├── routing_accuracy_eval.py # tracked: router determinism check
│   │   └── holdout_eval.py          # tracked: full pipeline on held-out set
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/             # testcontainers (real Postgres, no mocks)
│   ├── data/
│   │   ├── raw/                     # synthetic CSVs (generated, gitignored)
│   │   ├── processed/
│   │   └── models/                  # classifier.pkl (generated, gitignored)
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── types.ts                 # shared TypeScript types
│   │   ├── api/client.ts            # typed fetch wrapper + 401 interceptor
│   │   ├── features/
│   │   │   ├── auth/                # LoginForm, useAuth
│   │   │   ├── intake/              # IntakeTab, useIngestTicket
│   │   │   ├── resolution/          # ResolutionTab, ReclassifyPanel, useTickets, useWebSocket
│   │   │   ├── kb/                  # KBTab
│   │   │   ├── agent-sandbox/       # AgentTab (pipeline trace debugger)
│   │   │   └── analytics/           # AnalyticsTab (ticket metrics + bar charts)
│   │   ├── shared/                  # ConfidenceBadge, DomainBadge, ClassificationPanel, RoutingPanel
│   │   └── app/                     # App.tsx (tab shell + auth gate), routes.tsx
│   ├── Dockerfile
│   ├── Dockerfile.dev
│   └── package.json
├── docker/
│   ├── nginx.conf                   # SPA + API + WebSocket reverse proxy
│   ├── prometheus/prometheus.yml    # scrape config
│   └── grafana/
│       ├── provisioning/            # auto-provision datasource + dashboard
│       └── dashboards/ticketiq.json # 8-panel TicketIQ dashboard
├── docs/
│   ├── 00_PROBLEM_STATEMENT.md
│   ├── 01_LESSONS_LEARNED.md
│   ├── 02_ARCHITECTURE.md
│   ├── 03_BACKEND_DESIGN.md
│   ├── 04_FRONTEND_DESIGN.md
│   ├── 05_API_CONTRACT.md
│   ├── 06_DATA_AND_EVALUATION.md
│   └── 07_IMPLEMENTATION_PHASES.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example                     # document all env vars; commit this, not .env
└── CLAUDE.md                        # engineering conventions for this repo
```

---

## Prerequisites

### For Docker deployment (recommended)

- [Docker Engine](https://docs.docker.com/engine/install/) ≥ 24 and Docker Compose V2
- NVIDIA GPU + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) — **only** if using the `gpu` Compose profile for local Ollama. Skip entirely if using the Claude API or an external Ollama instance.

### For local development

- Python 3.11 (managed via [conda](https://conda.io/projects/conda/en/latest/) / [mamba](https://mamba.readthedocs.io/))
- Node.js 20+
- Docker (for the local PostgreSQL dev container)
- An Anthropic API key *or* a local Ollama instance with `mistral:7b-instruct` pulled

---

## Quick Start — Docker (recommended)

This brings up the full stack — PostgreSQL, API, React frontend, Prometheus, and
Grafana — with a single command.

### 1. Copy and fill in the environment file

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```dotenv
POSTGRES_PASSWORD=your_strong_db_password
ADMIN_PASSWORD=your_strong_admin_password   # must not be "changeme123", "password", or "admin"
JWT_SECRET_KEY=your_32_plus_character_secret_key

# Choose your LLM backend:
LLM_PROVIDER=ollama          # local  — also start the GPU profile below
# LLM_PROVIDER=claude        # cloud  — set ANTHROPIC_API_KEY instead
ANTHROPIC_API_KEY=           # only needed when LLM_PROVIDER=claude
```

### 2. Start the stack

**With Claude API (no GPU required):**

```bash
docker compose up --build -d
```

**With local Ollama on an NVIDIA GPU:**

```bash
# GPU profile starts the ollama service
docker compose --profile gpu up --build -d

# Pull the model (once, inside the container)
docker compose exec ollama ollama pull mistral:7b-instruct
```

### 3. Provision the database and seed data

```bash
# Create schema + indexes
docker compose exec api python scripts/setup_db.py

# Generate a labeled synthetic corpus and load it
# (requires ANTHROPIC_API_KEY even if LLM_PROVIDER=ollama — corpus generation always uses Claude)
docker compose exec api python scripts/generate_synthetic_data.py \
    --mode train --count 1200 --output data/raw/synthetic_train.csv

docker compose exec api python scripts/generate_synthetic_data.py \
    --mode test  --count 300  --output data/raw/synthetic_test.csv

docker compose exec api python scripts/load_tickets.py \
    --input-path data/raw/synthetic_train.csv \
    --source synthetic_train

docker compose exec api python scripts/load_tickets.py \
    --input-path data/raw/synthetic_test.csv \
    --source synthetic_test --ticket-source webhook

# Embed knowledge base entries
docker compose exec api python scripts/embed_knowledge_base.py

# Train the classifier
docker compose exec api python scripts/train_classifier.py
```

### 4. Open the application

| Service | URL |
|---|---|
| Frontend | http://localhost |
| API docs (Swagger) | http://localhost:8000/api/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin / `$GRAFANA_PASSWORD`) |

Log in with `admin` / `$ADMIN_PASSWORD` (the value you set in `.env`).

### Dev mode via Docker (hot reload, no local Python needed)

If you prefer Docker but still want hot reload, use the dev overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Changes to `backend/src/` and `frontend/src/` are reflected immediately (Uvicorn
`--reload`, Vite dev server). Prometheus runs on port `9091`, Grafana on `3001`.
Grafana anonymous admin access is enabled — no login required.

### Stopping the stack

```bash
docker compose down          # stop containers, keep volumes
docker compose down -v       # also remove all volumes (wipes DB and models)
```

---

## Local Development Setup

For development with hot reload and direct access to logs.

### 1. Python environment

```bash
mamba create -n ticketiq python=3.11
mamba activate ticketiq

cd backend
pip install -e ".[dev]"

# spaCy model required by Presidio's PII masker
python -m spacy download en_core_web_sm
```

### 2. PostgreSQL + pgvector (dev container)

Run the official pgvector image on a non-conflicting port:

```bash
docker run -d --name ticketiq-postgres \
    -p 5544:5432 \
    -e POSTGRES_USER=ticketiq \
    -e POSTGRES_PASSWORD=ticketiq_dev_pw \
    -e POSTGRES_DB=ticketiq \
    pgvector/pgvector:pg16
```

> **Docker permission error?**  
> Add your user to the `docker` group and pick up the change:
> ```bash
> sudo usermod -aG docker $USER
> newgrp docker
> ```

### 3. Environment variables

```bash
cd backend
cp .env.example .env
```

Minimum settings for local dev:

```dotenv
DATABASE_URL=postgresql+asyncpg://ticketiq:ticketiq_dev_pw@localhost:5544/ticketiq
ADMIN_PASSWORD=local_dev_password
JWT_SECRET_KEY=local_dev_secret_key_at_least_32_characters
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
ANTHROPIC_API_KEY=sk-ant-...    # needed for generate_synthetic_data.py
```

### 4. Database setup

```bash
cd backend
python scripts/setup_db.py
```

Idempotent — safe to re-run. Creates all six tables, enum types, the
`pgvector` extension, and the IVFFlat ANN index on `knowledge_base_entries`.

### 5. Generate & load synthetic data

```bash
# Training corpus (~1 200 tickets, 6 categories, ~30 % ambiguous)
python scripts/generate_synthetic_data.py \
    --mode train --count 1200 \
    --output data/raw/synthetic_train.csv

# Held-out test set (~300 harder tickets, never used for training)
python scripts/generate_synthetic_data.py \
    --mode test --count 300 \
    --output data/raw/synthetic_test.csv

# Load training set (CSV source — used for classifier training + KB seeding)
python scripts/load_tickets.py \
    --input-path data/raw/synthetic_train.csv \
    --source synthetic_train

# Load held-out set (WEBHOOK source — evaluation only, never used for training)
python scripts/load_tickets.py \
    --input-path data/raw/synthetic_test.csv \
    --source synthetic_test --ticket-source webhook
```

> `generate_synthetic_data.py` always uses the **Anthropic Claude API** regardless
> of `LLM_PROVIDER`, because Claude is the canonical synthetic corpus generator.
> Set `ANTHROPIC_API_KEY` in `.env` before running.

### 6. Embed the knowledge base

```bash
python scripts/embed_knowledge_base.py
```

Encodes all knowledge base entries (loaded with the training data) using
`sentence-transformers/all-MiniLM-L6-v2` and writes 384-dim vectors to
`knowledge_base_entries.embedding`.

### 7. Train the classifier

```bash
python scripts/train_classifier.py
# Output: data/models/classifier.pkl
```

Reads labeled CSV-source tickets from the DB, fits a TF-IDF + LinearSVC +
`CalibratedClassifierCV` pipeline, and saves it. The model is loaded at API
startup via `build_classifier(model_path)`.

### 8. Start the API

```bash
cd backend
uvicorn src.api.main:app --reload --port 8000
```

Swagger UI: http://localhost:8000/api/docs

### 9. Start the frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

The Vite dev server proxies `/api` and `/ws` to `localhost:8000` automatically
(configured in `vite.config.ts`).

---

## Running Tests

### Backend

```bash
cd backend
pytest                          # unit + integration
pytest tests/unit/              # unit only (no Docker needed)
pytest tests/integration/       # requires Docker (testcontainers)
pytest --cov=src --cov-report=term-missing
```

Integration tests spin up a real PostgreSQL 16 + pgvector container via
`testcontainers`. Ensure your user is in the `docker` group.

### Frontend

```bash
cd frontend
npm test             # single run (Vitest)
npm run test:watch   # watch mode
npm run lint         # tsc --noEmit + ESLint (zero-error gate)
```

---

## Evaluation Suite

All evaluators live in `backend/evaluation/`. Run from the `backend/` directory
with the virtual environment active and a `.env` file present.

| Evaluator | Command | Gate |
|---|---|---|
| Classifier F1 | `python evaluation/classification_eval.py` | CV F1 ≥ 0.92 |
| RAG Precision@5 | `python evaluation/rag_eval.py` | P@5 ≥ 0.80 |
| LLM Judge | `python evaluation/llm_judge.py` | Mean ≥ 3.5 / 5.0 |
| End-to-End latency | `python evaluation/end_to_end_eval.py` | p95 < 5 s |
| Routing accuracy | `python evaluation/routing_accuracy_eval.py` | Tracked only |
| Holdout pipeline | `python evaluation/holdout_eval.py` | Tracked only |

**Prerequisites:** `setup_db.py`, `load_tickets.py`, `embed_knowledge_base.py`,
and `train_classifier.py` must have been run. `llm_judge.py` and
`end_to_end_eval.py` also require an LLM backend (Ollama or Claude) running.
`holdout_eval.py` processes the held-out set and must run before `llm_judge.py`
can score its results.

**Recommended order:**

```bash
python evaluation/classification_eval.py
python evaluation/rag_eval.py
python evaluation/holdout_eval.py      # processes WEBHOOK tickets → must run first
python evaluation/llm_judge.py         # scores results from holdout_eval
python evaluation/end_to_end_eval.py
python evaluation/routing_accuracy_eval.py
```

Exit code `0` = gate passed (or metric is tracked-only). Exit code `1` = gate
failed; do not merge.

---

## API Reference

All endpoints are under `/api/v1`. Every response uses the standard envelope:

```json
{ "data": { ... } }                             // success, single resource
{ "data": [...], "meta": { "total": N, "offset": 0, "limit": 50 } }  // collection
{ "error": { "code": "...", "message": "...", "details": [...] } }    // error
```

### Authentication

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/token` | Log in (`application/x-www-form-urlencoded`: `username`, `password`). Returns `access_token`; sets `refresh_token` HttpOnly cookie. |
| `POST` | `/auth/refresh` | Rotate refresh token (reads cookie). Returns new access token. |
| `POST` | `/auth/logout` | Revoke refresh token. |

All other endpoints require `Authorization: Bearer <access_token>`.

### Tickets

| Method | Path | Description |
|---|---|---|
| `POST` | `/tickets/ingest` | Submit a ticket. Returns `202` immediately; pipeline runs in the background. |
| `GET` | `/tickets/{id}` | Get a ticket with classification + resolution. |
| `GET` | `/tickets/` | List tickets. Filters: `category`, `status`, `priority`, `offset`, `limit`. |
| `PATCH` | `/tickets/{id}/reclassify` | Override the category for an `awaiting_review` ticket. Resumes the pipeline. Body: `{"category": "infrastructure"}`. |

### Resolutions

| Method | Path | Description |
|---|---|---|
| `POST` | `/resolutions/{ticket_id}/feedback` | Submit resolution feedback. Body: `{"action": "accepted"\|"modified"\|"rejected", "modified_resolution": [...]}`. Returns `204`. |

### Health & Metrics

| Method | Path | Description |
|---|---|---|
| `GET` | `/health/live` | Liveness probe — always `200 OK` if the process is up. |
| `GET` | `/health/ready` | Readiness probe — `200` if DB is reachable, `503` otherwise. |
| `GET` | `/health/metrics` | Prometheus exposition format for scraping. |

### HTTP Status Code Reference

| Code | Situation |
|---|---|
| 200 | Successful read |
| 202 | Ticket queued / reclassification accepted |
| 204 | Feedback recorded (no body) |
| 400 / 422 | Validation failure |
| 401 | Unauthenticated |
| 403 | Authenticated but forbidden |
| 404 | Resource not found |
| 409 | Duplicate ticket (`DUPLICATE_TICKET`) or status conflict |
| 500 | Unhandled server error (details never exposed) |

---

## WebSocket

```
WS /ws/tickets/{ticket_id}
```

Streams every pipeline status transition to connected clients. No auth header
required on the socket itself — the token is validated on first connect.

**Events emitted by the server:**

```jsonc
{ "event": "status_changed", "ticket_id": "...", "status": "classifying" }
{ "event": "status_changed", "ticket_id": "...", "status": "awaiting_review" }
{ "event": "status_changed", "ticket_id": "...", "status": "retrieving" }
{ "event": "done",           "ticket_id": "...", "status": "auto_resolved" }
{ "event": "error",          "ticket_id": "...", "detail": "..." }
```

The `awaiting_review` event fires so the frontend can immediately render the
reclassification panel without a manual page refresh.

---

## Monitoring

### Prometheus metrics

All metrics use the `ticketiq_` prefix and are exposed at `/api/v1/health/metrics`.

| Metric | Type | Description |
|---|---|---|
| `ticketiq_tickets_processed_total` | Counter | Labels: `routing_decision`, `category`. Total tickets that exited the pipeline. |
| `ticketiq_awaiting_review_total` | Counter | Tickets parked at the pre-generation gate (v2 new status). |
| `ticketiq_ticket_duration_seconds` | Histogram | Label: `stage`. Per-stage wall-clock duration. |
| `ticketiq_classification_confidence` | Histogram | Top-1 confidence score per ticket (all tickets including awaiting_review). |
| `ticketiq_llm_quality_score` | Histogram | LLM evaluator quality score (1–5) for tickets that reached generation. |

**Useful PromQL queries:**

```promql
# Auto-resolve rate
sum(ticketiq_tickets_processed_total{routing_decision="auto_resolved"})
  / sum(ticketiq_tickets_processed_total)

# Awaiting-review rate
sum(ticketiq_tickets_processed_total{routing_decision="awaiting_review"})
  / sum(ticketiq_tickets_processed_total)

# p95 end-to-end latency (5-min window)
histogram_quantile(0.95, rate(ticketiq_ticket_duration_seconds_bucket[5m]))

# Throughput (tickets/min)
rate(ticketiq_tickets_processed_total[1m]) * 60
```

### Grafana

The Grafana dashboard at `docker/grafana/dashboards/ticketiq.json` is
automatically provisioned when the compose stack starts. Open
http://localhost:3000 (admin / `$GRAFANA_PASSWORD`).

**Panels included:**
- Tickets processed / min (time series, broken down by routing decision + category)
- Routing distribution (pie chart)
- Awaiting Review total (stat with threshold coloring)
- Pipeline duration p50 / p95 / p99 (time series)
- Classification confidence median (time series with green/yellow/red thresholds)
- LLM quality score median (time series)
- Auto-resolve rate (stat)
- Awaiting-review rate (stat)

---

## Environment Variables

### Docker Compose (`.env` at project root)

| Variable | Required | Default | Description |
|---|---|---|---|
| `POSTGRES_PASSWORD` | Yes | — | PostgreSQL password for the `ticketiq` user |
| `ADMIN_PASSWORD` | Yes | — | API admin account password. Must not be a known-weak value. |
| `JWT_SECRET_KEY` | Yes | — | JWT signing secret. Minimum 32 characters. |
| `LLM_PROVIDER` | No | `ollama` | `ollama` or `claude` |
| `OLLAMA_BASE_URL` | No | `http://ollama:11434` | Ollama API base URL |
| `ANTHROPIC_API_KEY` | Conditional | — | Required when `LLM_PROVIDER=claude` |
| `GRAFANA_PASSWORD` | No | `admin` | Grafana admin password |

### Backend (`.env` in `backend/`)

All variables documented with sample values in `backend/.env.example`. Key ones:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Async DSN: `postgresql+asyncpg://user:pass@host:port/db` |
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `CONFIDENCE_HIGH_THRESHOLD` | `0.85` | Classifier confidence above which a ticket is HIGH confidence |
| `CONFIDENCE_LOW_THRESHOLD` | `0.60` | Below this → LOW confidence → `AWAITING_REVIEW` |
| `MULTI_DOMAIN_DIFF_THRESHOLD` | `0.15` | Top-2 probability gap below which a ticket is multi-domain |
| `LLM_QUALITY_THRESHOLD` | `3.5` | Quality score below which a ticket is ESCALATED (not AUTO_RESOLVED) |
| `RAG_DENSE_WEIGHT` | `0.40` | Dense retrieval weight in the hybrid fusion |
| `RAG_BM25_WEIGHT` | `0.60` | BM25 retrieval weight in the hybrid fusion |
| `RAG_TOP_K` | `5` | Number of KB entries to pass to the LLM generator |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated list of allowed origins |
| `PROMETHEUS_ENABLED` | `true` | Enable Prometheus metric collection |

---

## Architecture Deep-Dive

Full design documentation lives in `docs/`:

| Document | Contents |
|---|---|
| [`00_PROBLEM_STATEMENT.md`](docs/00_PROBLEM_STATEMENT.md) | Hackathon brief and target metrics |
| [`01_LESSONS_LEARNED.md`](docs/01_LESSONS_LEARNED.md) | What v1 taught us — what changed and why |
| [`02_ARCHITECTURE.md`](docs/02_ARCHITECTURE.md) | System architecture, pipeline diagram, full tech stack |
| [`03_BACKEND_DESIGN.md`](docs/03_BACKEND_DESIGN.md) | Domain structure, DB schema, routing rules, auth, all audit fixes |
| [`04_FRONTEND_DESIGN.md`](docs/04_FRONTEND_DESIGN.md) | React/Vite architecture, feature structure, reclassification UI flow |
| [`05_API_CONTRACT.md`](docs/05_API_CONTRACT.md) | Complete endpoint contract with request/response shapes |
| [`06_DATA_AND_EVALUATION.md`](docs/06_DATA_AND_EVALUATION.md) | Synthetic data pipeline, classifier training, all six evaluators |
| [`07_IMPLEMENTATION_PHASES.md`](docs/07_IMPLEMENTATION_PHASES.md) | Phased build order with verification gates per phase |
| [`CLAUDE.md`](CLAUDE.md) | Engineering conventions — TypeScript strict mode, layered architecture, response envelope, commit format |
