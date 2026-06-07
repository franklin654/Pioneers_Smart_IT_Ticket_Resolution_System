# TicketIQ — Backend

AI-Powered Intelligent Ticket Routing & Resolution Agent
**NASSCOM Hackathon — Trail Blazers**

---

## Overview

TicketIQ is a FastAPI backend that automates the full IT support ticket lifecycle:

```text
Ticket In
    │
    ▼
[Ingestion]      — validate, PII-mask, deduplicate
    │
    ▼
[Classifier]     — sentence-transformers + LogisticRegression, 6 categories
    │
    ▼
[RAG Pipeline]   — 70% pgvector dense + 30% BM25, MMR reranking
    │
    ▼
[LLM Generator]  — Ollama (Mistral-7B) or Claude API
    │
    ▼
[Evaluator]      — LLM-as-judge (relevance + completeness + actionability, 0–5)
    │
    ├── Score ≥ 3.5 + HIGH confidence  → AUTO_RESOLVED
    ├── Score ≥ 3.5 + MEDIUM confidence → ASSIGNED
    └── Score < 3.5 or multi-domain   → ESCALATED
```

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| API | FastAPI 0.111 (async) + uvicorn |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16 + pgvector |
| Embedding | sentence-transformers/all-MiniLM-L6-v2 (384-dim) |
| Classifier | scikit-learn LogisticRegression |
| BM25 | rank-bm25 |
| LLM | Ollama (Mistral-7B) / Claude API — env-controlled |
| Agents | AutoGen v2 (ag2) GroupChat |
| PII Detection | Microsoft Presidio |
| Auth | JWT HS256 (python-jose) + PBKDF2-SHA256 passwords |
| Monitoring | Prometheus + Grafana |
| Testing | pytest + pytest-asyncio |
| Python | >= 3.11 |

---

## Project Structure

```text
backend/
├── src/
│   ├── core/           — config (Settings), logging, exceptions
│   ├── db/             — SQLAlchemy models, session, 5 repositories
│   ├── schemas/        — Pydantic v2 request/response schemas
│   ├── ingestion/      — validator, PII masker, deduplicator, pipeline
│   ├── embedding/      — sentence-transformers generator + pgvector store
│   ├── classification/ — LogisticRegression classifier, confidence scoring
│   ├── rag/            — hybrid retriever, MMR reranker, LLM generators, KB
│   ├── agents/         — AutoGen orchestrator + 4 agents
│   ├── routing/        — routing decision engine, escalation detection
│   ├── api/            — FastAPI routes, middleware, WebSocket, metrics
│   └── monitoring/     — Prometheus metric definitions
├── evaluation/         — 4 evaluators + unified runner
├── scripts/            — DB setup, data loading, classifier training
├── tests/              — unit/ and integration/ test suites
├── data/               — raw CSVs, trained models, processed outputs
├── Dockerfile
└── pyproject.toml
```

---

## Prerequisites

- Python >= 3.11 (conda/mamba environment recommended)
- PostgreSQL 16 with pgvector extension
- [Ollama](https://ollama.com) running locally **or** an `ANTHROPIC_API_KEY`

---

## Quick Start

### 1. Create environment and install dependencies

```bash
mamba create -n ticket_routing python=3.11
mamba activate ticket_routing
pip install -e ".[dev]"
```

### 2. Configure environment variables

```bash
cp ../../.env.example ../../.env
# Edit .env — at minimum set:
#   DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/ticket_routing
#   SECRET_KEY=<random string, minimum 32 characters>
#   LLM_BACKEND=ollama   (or "claude" + ANTHROPIC_API_KEY)
```

### 3. Initialise the database

```bash
python -m scripts.setup_db
```

### 4. Load training data

```bash
# Option A — Kaggle IT support dataset (place CSV at data/raw/tickets.csv)
python -m scripts.load_kaggle_data --input-path data/raw/tickets.csv

# Option B — Generate synthetic data via Claude API
python -m scripts.generate_synthetic_data --count 500 --output data/raw/synthetic.csv
python -m scripts.load_kaggle_data --input-path data/raw/synthetic.csv
```

### 5. Train the classifier

```bash
python -m scripts.train_classifier
# Saves artifact to data/models/classifier.pkl
```

### 6. Index the knowledge base

```bash
python -m scripts.index_knowledge_base
# Builds BM25 index from KB entries in the database
```

### 7. Start the API

```bash
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

API: `http://localhost:8000`
Swagger UI: `http://localhost:8000/docs`

---

## Docker (full stack)

```bash
cd ../docker
docker compose up --build
```

| Service | URL | Credentials |
| --- | --- | --- |
| API | <http://localhost:8000> | — |
| Swagger UI | <http://localhost:8000/docs> | — |
| Prometheus Metrics | <http://localhost:8000/metrics> | — |
| Prometheus | <http://localhost:9090> | — |
| Grafana | <http://localhost:3000> | admin / admin |

**GPU profile** (Ollama with NVIDIA GPU):

```bash
docker compose --profile gpu up --build
```

**Development mode** (hot-reload, DB port exposed):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

---

## API Reference

Full contract: [`../../API_CONTRACT.md`](../../API_CONTRACT.md)
Interactive docs: `http://localhost:8000/docs`

### Authentication

```bash
# Get JWT token (OAuth2 form-data)
curl -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin&password=changeme123"
```

### Key Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/token` | — | Login -> JWT |
| `POST` | `/api/v1/tickets/ingest` | Bearer | Submit ticket (202 async) |
| `GET` | `/api/v1/tickets/{id}` | — | Full detail with classification + resolution |
| `GET` | `/api/v1/tickets/` | — | Paginated list with filters |
| `POST` | `/api/v1/resolutions/{id}/feedback` | Bearer | Agent feedback (204) |
| `WS` | `/ws/tickets/{id}` | — | Live status stream |
| `GET` | `/health/live` | — | Liveness probe |
| `GET` | `/health/ready` | — | Readiness probe |
| `GET` | `/metrics` | — | Prometheus metrics |

---

## Configuration Reference

All settings are loaded from `.env`. See `src/core/config.py` for full definitions.

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | required | asyncpg PostgreSQL DSN |
| `SECRET_KEY` | required (>= 32 chars) | JWT signing key |
| `LLM_BACKEND` | `ollama` | `"ollama"` or `"claude"` |
| `ANTHROPIC_API_KEY` | `""` | Required when `LLM_BACKEND=claude` |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `mistral:7b-instruct` | Ollama model tag |
| `ADMIN_USERNAME` | `admin` | Demo login username |
| `ADMIN_PASSWORD` | `changeme123` | Demo login password |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `CONFIDENCE_HIGH_THRESHOLD` | `0.85` | HIGH confidence cutoff |
| `CONFIDENCE_LOW_THRESHOLD` | `0.60` | LOW confidence cutoff |
| `RAG_TOP_K` | `5` | Final retrieved entries per query |
| `RAG_DENSE_WEIGHT` | `0.70` | pgvector weight in hybrid retrieval |
| `RAG_BM25_WEIGHT` | `0.30` | BM25 weight in hybrid retrieval |
| `RATE_LIMIT_PER_MINUTE` | `100` | Requests per IP per 60 s |
| `CORS_ORIGINS` | `["http://localhost:4200"]` | Allowed CORS origins |

---

## Running Tests

```bash
# Unit tests only (no DB or ML models required)
mamba run -n ticket_routing python -m pytest tests/unit/ -v

# Full suite with coverage report
mamba run -n ticket_routing python -m pytest

# Skip slow tests (Presidio/spaCy model loading)
mamba run -n ticket_routing python -m pytest -m "not slow"
```

Current state: **396 tests passing | 73.26% coverage**

---

## Evaluation Suite

Validates all six target metrics. Requires a populated database with processed tickets.

```bash
# Run all four evaluators in sequence
python -m evaluation.run_all

# Individual evaluators
python -m evaluation.classification_eval --fail-under 0.92
python -m evaluation.rag_eval --top-k 5 --fail-under-precision 0.80
python -m evaluation.llm_judge --fail-under 3.5
python -m evaluation.end_to_end_eval --fail-latency 5.0 --fail-auto-resolve 25.0
```

| Metric | Target |
| --- | --- |
| Classification Macro F1 | >= 0.92 |
| RAG Precision@5 | >= 0.80 |
| RAG MRR | >= 0.70 |
| LLM Quality Score (mean) | >= 3.5 / 5.0 |
| Auto-Resolve Rate | >= 25% |
| E2E Latency p95 | < 5 s |

---

## Routing Logic

| Confidence | Multi-domain | LLM Score | Decision |
| --- | --- | --- | --- |
| HIGH (>= 0.85) | No | >= 3.5 | AUTO_RESOLVED |
| HIGH or MEDIUM | No | >= 3.5 | ASSIGNED |
| Any | Yes | Any | ESCALATED |
| Any | No | < 3.5 | ESCALATED |
| LOW (< 0.60) | No | Any | ESCALATED |

---

## Database Models

| Model | Purpose |
| --- | --- |
| `Ticket` | Core ticket record (title, description, category, priority, status, pii_detected) |
| `Classification` | Classifier output (predicted_category, confidence, confidence_level, is_multi_domain) |
| `Resolution` | Agent output (suggested_steps, llm_quality_score, routing_decision, assigned_department) |
| `FeedbackLog` | Agent feedback on resolutions (accepted / modified / rejected) |
| `KnowledgeBaseEntry` | Historical resolutions used by RAG (with 384-dim embedding) |
| `TicketEmbedding` | pgvector embedding for each ticket (384-dim) |

---

## Prometheus Metrics

Exposed at `GET /metrics`. Scraped every 15 s.

| Metric | Type | Labels |
| --- | --- | --- |
| `http_requests_total` | Counter | method, path, status_code |
| `http_request_duration_seconds` | Histogram | method, path |
| `tickets_ingested_total` | Counter | source, category |
| `ticket_processing_duration_seconds` | Histogram | routing_decision |
| `classification_confidence` | Histogram | category, confidence_level |
| `llm_quality_score` | Histogram | routing_decision |
| `auto_resolve_rate` | Gauge | — |

---

## Code Quality

```bash
# Lint
ruff check src/ tests/

# Type-check
mypy src/

# Format
ruff format src/ tests/
```
