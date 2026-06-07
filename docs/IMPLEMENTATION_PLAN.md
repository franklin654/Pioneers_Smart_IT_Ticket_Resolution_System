# Implementation Plan: AI-Powered Intelligent Ticket Routing & Resolution Agent

## NASSCOM Hackathon — Trail Blazers

---

## Problem Statement

IT service companies receive thousands of support tickets daily, suffering from:

- Misrouted tickets
- Slow resolution
- Poor categorization
- Manual triaging

This system automates the full lifecycle: **ingest → classify → retrieve similar resolutions → generate fix → route or escalate** — with tracked confidence scores.

---

## Architecture Overview

```
Ticket In
    │
    ▼
[Ingestion Pipeline]  ← validate, PII mask, deduplicate
    │
    ▼
[Embedding Generator] ← sentence-transformers/all-MiniLM-L6-v2
    │
    ├──► [Classifier]  ← LinearSVC (calibrated) on embeddings
    │         │
    │         ▼
    │    [Confidence Scorer]
    │         │
    │    ┌────┴────┐
    │  HIGH     LOW / MULTI-DOMAIN
    │    │           │
    │    ▼           ▼
    │  [RAG]      [ESCALATE]
    │    │
    │    ├── Dense retrieval (pgvector 70%)
    │    ├── BM25 keyword retrieval (30%)
    │    └── MMR reranking (λ=0.7)
    │         │
    │         ▼
    │    [LLM Generator]  ← Ollama (Mistral-7B) or Claude API
    │         │
    │         ▼
    │    [Evaluator Agent]  ← LLM-as-judge scoring
    │         │
    │    ┌────┴──────┐
    │ score≥3.5   score<3.5
    │    │              │
    ▼    ▼              ▼
AUTO_RESOLVE   ASSIGNED   ESCALATED
```

**Target Metrics:**

- Classification F1: ≥ 0.92
- RAG Precision@5: ≥ 80%
- LLM Quality Score: ≥ 3.5/5.0
- Auto-Resolve Rate: ≥ 25%
- E2E Latency p95: < 5s

---

## Technology Stack

| Layer | Technology |
|---|---|
| API | FastAPI (async) |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16 + pgvector |
| Embedding | sentence-transformers/all-MiniLM-L6-v2 (384-dim) |
| Classifier | scikit-learn LinearSVC + CalibratedClassifierCV |
| BM25 | rank-bm25 |
| LLM | Ollama (Mistral-7B) / Claude API — env-controlled |
| Agents | AutoGen (pyautogen) GroupChat |
| PII Detection | Microsoft Presidio |
| Auth | PyJWT + bcrypt |
| Frontend | Angular 17 + Angular Material |
| Monitoring | Prometheus + Grafana |
| Deployment | Docker Compose |
| Testing | pytest + pytest-asyncio |

---

## Project Structure

```
app_v2/
├── backend/
│   ├── src/
│   │   ├── core/           # config, logging, exceptions
│   │   ├── db/             # SQLAlchemy models, session, repositories
│   │   ├── schemas/        # Pydantic v2 request/response schemas
│   │   ├── ingestion/      # validator, PII masker, deduplicator, pipeline
│   │   ├── embedding/      # sentence-transformers generator, pgvector store
│   │   ├── classification/ # LinearSVC classifier, trainer, confidence
│   │   ├── rag/            # hybrid retriever, MMR reranker, LLM generator, KB
│   │   ├── agents/         # AutoGen orchestrator + 4 agents
│   │   ├── routing/        # routing decision engine, escalation logic
│   │   ├── api/            # FastAPI routes, middleware, WebSocket
│   │   └── monitoring/     # Prometheus metrics, health checks
│   ├── scripts/            # setup_db, generate_synthetic_data, load_tickets, train_classifier, etc.
│   ├── data/               # raw/ (synthetic CSVs), processed/, models/
│   ├── tests/              # unit/, integration/, conftest.py
│   ├── evaluation/         # classification_eval, rag_eval, llm_judge, e2e_eval
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/               # Angular 17 SPA
│   ├── src/app/
│   │   ├── core/           # services, interceptors, models
│   │   ├── features/       # ticket-submit, ticket-status, dashboard
│   │   └── shared/         # reusable components
│   └── Dockerfile
├── docker/
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   ├── prometheus.yml
│   └── grafana/
├── .env.example
├── IMPLEMENTATION_PLAN.md
└── README.md
```

---

## Implementation Phases

### Phase 1 — Project Scaffolding & Data Foundation

**Goal:** Complete project skeleton, PostgreSQL + pgvector schema, all ORM models, repository layer, and Kaggle data loader.

**Deliverables:**

- `pyproject.toml` with all dependencies
- `core/config.py` — Pydantic Settings (env-driven, all LLM/DB/auth config)
- `core/logging.py` — structured JSON logging
- `core/exceptions.py` — full exception hierarchy
- `db/models.py` — 6 SQLAlchemy ORM models with pgvector columns
- `db/database.py` — async session factory
- `db/repositories/` — generic BaseRepository + 4 domain repositories
- `schemas/` — Pydantic v2 request/response schemas
- `scripts/setup_db.py` — idempotent DB init + pgvector + IVFFlat indexes
- `scripts/generate_synthetic_data.py` — Claude API synthetic ticket generator (train + test modes)
- `scripts/load_tickets.py` — synthetic CSV → DB loader (supports training and held-out test set)
- `docker/docker-compose.yml` — full service stack
- `.env.example`
- Unit + integration tests for all of the above

---

### Phase 2 — Ingestion Pipeline

**Goal:** Validated, PII-masked, deduplicated ticket intake.

**Deliverables:**

- `ingestion/validator.py` — Pydantic schema validation + sanitization
- `ingestion/pii_masker.py` — Presidio wrapper (8 entity types)
- `ingestion/deduplicator.py` — MD5 exact match + embedding near-duplicate (0.95 threshold)
- `ingestion/pipeline.py` — 6-stage orchestrator, <205ms latency target
- Full unit + integration test coverage

---

### Phase 3 — Embedding & Classification

**Goal:** Trained classifier achieving F1 ≥ 0.92 across 6 IT ticket categories.

**Deliverables:**

- `embedding/generator.py` — sentence-transformers inference (<50ms)
- `embedding/store.py` — pgvector upsert + ANN similarity search
- `classification/trainer.py` — LinearSVC training pipeline
- `classification/classifier.py` — inference + top-3 probabilities (<22ms)
- `classification/confidence.py` — HIGH/MEDIUM/LOW levels + multi-domain detection
- `scripts/train_classifier.py` — end-to-end training run
- Evaluation: F1, accuracy, confusion matrix

---

### Phase 4 — RAG Pipeline

**Goal:** Hybrid retrieval + LLM generation with configurable backend.

**Deliverables:**

- `rag/knowledge_base.py` — indexing + BM25 build + feedback updates
- `rag/retriever.py` — 70% dense (pgvector) + 30% BM25 fusion
- `rag/reranker.py` — MMR reranking (λ=0.7)
- `rag/generator.py` — `OllamaGenerator` + `ClaudeGenerator` behind `LLMGeneratorProtocol`; `LLMGeneratorFactory` reads `LLM_BACKEND` env
- Prompt templates per category
- Evaluation: Precision@5 ≥ 0.80, Recall@5 ≥ 0.85, MRR ≥ 0.70

---

### Phase 5 — Agentic Orchestration

**Goal:** AutoGen multi-agent workflow driving the full ticket lifecycle.

**Deliverables:**

- `agents/orchestrator.py` — AutoGen GroupChat, ticket state machine
- `agents/classifier_agent.py`
- `agents/rag_agent.py`
- `agents/evaluator_agent.py` — LLM-as-judge (Relevance + Completeness + Actionability)
- `agents/user_proxy.py` — routing enforcement
- `routing/router.py` — AUTO_RESOLVED / ASSIGNED / ESCALATED decision engine
- `routing/escalation.py` — repeated-issue detection + automation suggestion

---

### Phase 6 — API Layer

**Goal:** Production-quality FastAPI REST + WebSocket API.

**Deliverables:**

- `api/main.py` — app setup, lifespan, middleware, versioning
- `api/routes/tickets.py` — POST /ingest, GET /{id}, GET / (paginated)
- `api/routes/resolutions.py` — POST /feedback
- `api/routes/health.py` — liveness + readiness
- `api/websocket.py` — `WS /ws/tickets/{id}`, state-transition events
- `api/middleware/auth.py` — JWT Bearer + RBAC (L1/L2/L3/Admin)
- `api/middleware/rate_limiter.py` — 100 req/min sliding window

---

### Phase 7 — Angular Frontend

**Goal:** SPA with ticket submission, live status, and KPI dashboard.

**Deliverables:**

- Angular 17 project with Angular Material
- `core/services/` — TicketService, AuthService, WebSocketService
- `features/ticket-submit/` — validated form
- `features/ticket-status/` — confidence visualization, agent trace, feedback controls
- `features/dashboard/` — KPI cards, category chart, recent tickets table
- Multi-stage Dockerfile (node build → nginx serve)

---

### Phase 8 — Evaluation Suite

**Goal:** Reproducible metric validation proving all targets are met.

**Deliverables:**

- `evaluation/classification_eval.py` — F1, accuracy, confusion matrix (gate: F1 ≥ 0.90)
- `evaluation/rag_eval.py` — P@k, R@k, MRR
- `evaluation/llm_judge.py` — LLM-as-judge scoring distribution
- `evaluation/end_to_end_eval.py` — latency p50/p95/p99, routing distribution

---

### Phase 9 — Docker & Monitoring

**Goal:** Single `docker compose up` brings full system online.

**Deliverables:**

- `docker-compose.yml` — postgres, api, frontend, prometheus, grafana, ollama (gpu profile)
- `docker-compose.dev.yml` — source mounts + hot-reload
- Prometheus metrics: tickets_processed_total, ticket_processing_duration_seconds, classification_confidence, llm_quality_score, auto_resolve_rate
- Grafana dashboards: System Health, ML Performance, Business KPIs, Ticket Processing

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Vector store | PostgreSQL + pgvector | No extra service; native joins with ticket data |
| Classifier | LinearSVC + CalibratedClassifierCV on embeddings | <5ms inference, strong F1 ≥ 0.92, `predict_proba` via calibration |
| Retrieval | Hybrid 70% dense + 30% BM25 | +7% precision gain vs dense-only (from ablation) |
| LLM backend | Env-controlled (`LLM_BACKEND`) | Offline (Ollama) for demo; Claude API as fallback |
| Auth | JWT HS256 | Stateless, RBAC-compatible, no session store |
| Frontend | Angular 17 + REST/WebSocket | Real-time updates, component-based SPA |

---

## Confidence Threshold Logic

| Confidence | Is Multi-Domain | LLM Score | Routing Decision |
|---|---|---|---|
| HIGH (≥0.85) | No | ≥ 3.5 | AUTO_RESOLVED |
| HIGH or MEDIUM | No | ≥ 3.5 | ASSIGNED + suggestion |
| Any | Yes | Any | ESCALATED |
| Any | No | < 3.5 | ESCALATED |
| LOW (< 0.60) | No | Any | ESCALATED |

---

## Category → Department Mapping

| Category | Department Queue |
|---|---|
| infrastructure | infra-team |
| application | app-team |
| security | security-team |
| database | db-team |
| access_management | iam-team |
| network | network-team |
