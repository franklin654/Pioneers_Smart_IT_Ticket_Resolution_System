# TicketIQ — Project Summary
## NASSCOM Hackathon · Trail Blazers Team

**Last updated:** 2026-06-08  
**Working directory:** root of repo  
**Backend root:** `backend/`

---

## 1. What Was Built

**TicketIQ** is an AI-powered IT ticket routing and resolution agent. It automates the full ticket lifecycle:

```
Ingest → Validate/Deduplicate → Embed → Classify → RAG Retrieve → LLM Generate → Route/Escalate
```

Tickets enter via REST API, are classified into one of 6 categories with a confidence score, matched against a knowledge base using hybrid retrieval, and resolved or escalated automatically based on LLM quality scoring.

---

## 2. Architecture

```
Ticket In
    │
    ▼
[Ingestion Pipeline]  ← validate, PII mask, deduplicate (SHA-256 hash)
    │
    ▼
[Embedding Generator] ← sentence-transformers/all-MiniLM-L6-v2 (384-dim)
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
    │    ├── Dense retrieval  (pgvector cosine, 70% weight)
    │    ├── BM25 keyword     (rank-bm25, 30% weight)
    │    └── MMR reranking    (λ=0.7 relevance/diversity)
    │         │
    │         ▼
    │    [LLM Generator]  ← Ollama Mistral-7B or Claude API (env-controlled)
    │         │
    │         ▼
    │    [Evaluator Agent]  ← LLM-as-judge (1–5 score)
    │         │
    │    ┌────┴──────┐
    │ score≥3.5   score<3.5
    ▼    ▼              ▼
AUTO_RESOLVE   ASSIGNED   ESCALATED
```

### Ticket Categories (6)
`INFRASTRUCTURE` · `APPLICATION` · `SECURITY` · `DATABASE` · `ACCESS_MANAGEMENT` · `NETWORK`

### Technology Stack

| Layer | Technology |
| --- | --- |
| API | FastAPI (async) |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Database | PostgreSQL 16 + pgvector extension |
| Embedding | sentence-transformers/all-MiniLM-L6-v2 (384-dim) |
| Classifier | scikit-learn LinearSVC + CalibratedClassifierCV |
| BM25 index | rank-bm25 |
| LLM | Ollama (Mistral-7B) / Claude API — switched via `LLM_BACKEND` env var |
| Agent orchestration | AutoGen (pyautogen) GroupChat, 4 agents |
| Frontend | Angular 20 + Material UI |
| Monitoring | Prometheus metrics + Grafana dashboards |
| Container | Docker Compose (backend, postgres, ollama, prometheus, grafana) |

### Target Metrics

| Metric | Target |
| --- | --- |
| Classification Macro F1 | ≥ 0.92 |
| RAG Precision@5 | ≥ 80% |
| LLM Quality Score | ≥ 3.5 / 5.0 |
| Auto-Resolve Rate | ≥ 25% |
| E2E Latency p95 | < 5 s |
| Routing Accuracy | ≥ 75% |

---

## 3. Implementation Phases

All 10 phases are complete.

### Phase 1 — Scaffolding
**Files:** `src/db/models.py`, `src/db/repositories/`, `src/core/config.py`, `src/core/logging.py`, `docker-compose.yml`, `pyproject.toml`

- PostgreSQL schema: `tickets`, `ticket_classifications`, `ticket_resolutions`, `knowledge_base_entries`, `feedback_logs`
- pgvector `IVFFlat` index on `knowledge_base_entries.embedding` (lists=100, later tunable to 200–300 at 82K+ entries)
- Pydantic Settings with `extra="ignore"` — allows Docker-specific env vars (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `GRAFANA_PASSWORD`) in the same `.env` without validation errors
- `TicketSource` enum: `CSV` (training data), `API` (live tickets), `WEBHOOK` (reserved — repurposed in Phase 10 for held-out test set)
- `TicketCategory` enum: 6 values above
- `TicketStatus` enum: `OPEN`, `IN_PROGRESS`, `CLOSED`, `ESCALATED`

### Phase 2 — Ingestion Pipeline
**Files:** `src/services/ingestion.py`

- Input validation (Pydantic schemas)
- PII masking (emails, phone numbers, IP addresses replaced with placeholders)
- Content deduplication: SHA-256 hash of `title + description`; duplicate tickets within `dedup_window_days` are rejected
- Confidence thresholds: `confidence_high_threshold=0.85`, `confidence_low_threshold=0.60`, `multi_domain_diff_threshold=0.15`

### Phase 3 — Classification
**Files:** `src/services/classifier.py`, `scripts/train_classifier.py`

- `EmbeddingService`: wraps `SentenceTransformer`, batch-encodes with `embedding_batch_size=32`
- `ClassifierService`: loads `data/models/classifier.pkl` (LinearSVC + CalibratedClassifierCV trained on embedded ticket text)
- Training script reads all labeled tickets from DB, encodes them, trains with an 80/20 split, gates on macro F1 ≥ 0.90
- Multi-domain detection: if top-2 class probability gap < `multi_domain_diff_threshold`, ticket is flagged multi-domain → escalated

### Phase 4 — RAG & LLM
**Files:** `src/services/retriever.py`, `src/services/llm.py`, `scripts/index_knowledge_base.py`

- Hybrid retrieval: dense (pgvector cosine) + BM25 keyword, weighted 70/30
- MMR reranking: selects top-k from a `rag_candidate_pool=20` pool balancing relevance (λ=0.7) vs diversity
- LLM backends: Ollama (default, `mistral:7b-instruct`) or Claude (`claude-haiku-4-5-20251001`), switched by `LLM_BACKEND` in `.env`
- KB indexing script: builds BM25 pickle from all `KnowledgeBaseEntry` rows

### Phase 5 — Agent Orchestration
**Files:** `src/agents/`

- AutoGen `GroupChat` with 4 agents: Coordinator, Classifier Agent, RAG Agent, Escalation Agent
- Agents communicate over the GroupChat; Coordinator routes tickets based on confidence score and LLM quality gate
- Resolution stored in `ticket_resolutions`, status updated to `AUTO_RESOLVE` / `ASSIGNED` / `ESCALATED`

### Phase 6 — API
**Files:** `src/api/main.py`, `src/api/routes/`, `src/api/schemas/`

- FastAPI async REST API
- JWT auth (`HS256`, 60-min access tokens, 7-day refresh tokens)
- Key endpoints:
  - `POST /api/v1/tickets/ingest` — full pipeline ingestion
  - `GET /api/v1/tickets/{id}` — ticket detail
  - `GET /api/v1/tickets/` — paginated list with filters
  - `POST /api/v1/auth/token` — login
  - `GET /health/ready` — readiness probe
- WebSocket endpoint for real-time ticket status updates
- Rate limiting: 100 req/min

### Phase 7 — Frontend
**Files:** `frontend/src/`

- Angular 20 SPA, Material UI components
- Dashboard: live ticket feed, category distribution charts, auto-resolve rate gauge
- Ticket detail view: classification confidence bar, RAG sources panel, LLM resolution display
- WebSocket-connected for real-time status updates

### Phase 8 — Evaluation Suite
**Files:** `evaluation/classification_eval.py`, `evaluation/rag_eval.py`, `evaluation/llm_judge.py`, `evaluation/end_to_end_eval.py`, `evaluation/run_all.py`

Four evaluators, each with a CLI gate (`--fail-under`) and `sys.exit(1)` on failure:

| Evaluator | Metric | Gate |
| --- | --- | --- |
| `classification_eval.py` | Macro F1 on test split | ≥ 0.92 |
| `rag_eval.py` | Precision@5 | ≥ 0.80 |
| `llm_judge.py` | Mean LLM-as-judge score | ≥ 3.5 |
| `end_to_end_eval.py` | p95 latency | < 5.0 s |

`run_all.py` runs all four sequentially and prints a summary table.

### Phase 9 — Docker & Monitoring
**Files:** `docker/docker-compose.yml`, `docker/prometheus.yml`, `docker/grafana/`

- Docker Compose services: `backend`, `postgres` (pgvector image), `ollama` (GPU profile), `prometheus`, `grafana`
- Prometheus scrapes `/metrics` from the backend (FastAPI instrumented)
- Grafana dashboards: ticket throughput, classification distribution, latency percentiles, auto-resolve rate
- Health check: `GET /health/ready` → `{"status":"ready","database":"ok"}`
- `.env` includes both asyncpg `DATABASE_URL` (used by Python) and plain `POSTGRES_*` vars (used by Docker Compose) — Pydantic ignores the Docker vars via `extra="ignore"`

### Phase 10 — Synthetic Data Pipeline & 5th Evaluator
**Files modified:** `scripts/load_tickets.py` (renamed from `load_kaggle_data.py`), `src/db/repositories/ticket_repo.py`, `evaluation/run_all.py`, `pyproject.toml`  
**Files created:** `evaluation/routing_accuracy_eval.py`  
**Files deleted:** `scripts/load_uci_incidents.py`, `scripts/load_servicenow_test_set.py`

Goal: replace external dataset dependency with a fully synthetic data pipeline and add a 5th evaluator.

**Key additions:**

1. **`generate_synthetic_data.py` — two generation modes**
   - `--mode train`: uses `CATEGORY_SCENARIOS` (standard realistic issues); outputs title/description/category/resolution/priority CSV
   - `--mode test`: uses `TEST_CATEGORY_SCENARIOS` (harder edge cases — e.g. NTP clock drift, BGP route flapping); outputs title/description/category/priority CSV (no resolution column)
   - Balanced generation: `--count N` distributed evenly across 6 categories
   - `--categories` flag for targeted generation

2. **`load_tickets.py`** — generic synthetic CSV loader
   - `--ticket-source csv` (default): training data — inserts tickets + `KnowledgeBaseEntry` rows (if resolution column present)
   - `--ticket-source webhook`: held-out test set — inserts tickets only (no KB entries); isolated from training by `TicketSource.WEBHOOK` discriminator
   - `--source` flag: tags `KnowledgeBaseEntry.source` for traceability

3. **`ticket_repo.get_by_source()`** — repo method querying by `TicketSource` enum

4. **`routing_accuracy_eval.py`** — 5th evaluator
   - Queries `TicketSource.WEBHOOK` tickets with classification loaded
   - Compares `predicted_category` vs `ticket.category` (ground truth)
   - Per-category accuracy table across all 6 categories
   - Gate: overall accuracy ≥ `fail_under` (default 0.75)

5. **`run_all.py`** updated to run 5/5 evaluators with `--fail-under-routing` CLI option

---

## 4. Key Technical Decisions & Fixes

### Pydantic Settings `extra="ignore"`
Docker Compose env vars (`POSTGRES_DB`, `POSTGRES_USER`, etc.) in the shared `.env` caused `ValidationError: extra key not allowed` on startup. Fixed by adding `extra="ignore"` to `SettingsConfigDict` in `src/core/config.py`.

### Content Hash Deduplication
SHA-256 of `title.strip().lower() + "::" + description.strip().lower()`. Prevents re-inserting identical tickets if `load_tickets.py` is run more than once against the same CSV.

### Synthetic Held-Out Test Set Strategy
`generate_synthetic_data.py --mode test` generates harder scenarios (e.g. BGP route flapping, autovacuum bloat, PAM misconfiguration) without resolution text, so the pipeline cannot cheat by pattern-matching the answer. Loaded via `load_tickets.py --ticket-source webhook` to tag rows as `TicketSource.WEBHOOK` — the `routing_accuracy_eval.py` evaluator uses this discriminator to isolate them from training data.

### pgvector IVFFlat Index Tuning
At small synthetic data volumes the default `lists=100` is more than adequate. If KB entries grow beyond 50K, tune to `lists=200` for better recall/performance.

---

## 5. Synthetic Data Pipeline

### Generated Files in `backend/data/raw/`

| File | Rows | Mode | Notes |
| --- | --- | --- | --- |
| `synthetic_train.csv` | ~1,200 | `--mode train` | 200 per category; includes resolution column; loaded as CSV source |
| `synthetic_test.csv` | ~300 | `--mode test` | 50 per category; harder edge cases; no resolution column; loaded as WEBHOOK source |

### Data Volumes

| Source | Rows | IT-labeled | Notes |
| --- | --- | --- | --- |
| Synthetic training | ~1,200 | 1,200 | All 6 categories, balanced, includes resolutions → KB entries |
| **Total training** | **~1,200** | **~1,200** | All rows fully labeled |
| Synthetic test set (held-out) | ~300 | 300 | `TicketSource.WEBHOOK` — evaluation only, never trained on |

---

## 6. Database State

### DB Connection
```
postgresql+asyncpg://<user>:<password>@localhost:5432/ticket_routing
```
(Set via `DATABASE_URL` in `.env`.)

### Schema Highlights
- `tickets.content_hash` — SHA-256 dedup key; unique constraint prevents re-inserting identical tickets
- `tickets.source` — `TicketSource` enum; `WEBHOOK` is reserved for the held-out test set; `CSV` for training data
- `knowledge_base_entries.source` — free-text string (e.g. `"synthetic_train"`) for traceability
- `knowledge_base_entries.embedding` — `vector(384)` with IVFFlat index

---

## 7. How to Run the Full Pipeline

All commands run from `backend/` with the Python environment active.

### Setup (once)
```bash
pip install -e ".[dev]"
python -m scripts.setup_db
```

### Generate & Load Training Data
```bash
# Generate 1,200 synthetic training tickets (200 per category)
python -m scripts.generate_synthetic_data \
  --mode train --count 1200 --output data/raw/synthetic_train.csv

# Load training tickets + KB entries
python -m scripts.load_tickets \
  --input-path data/raw/synthetic_train.csv --source synthetic_train
```

### Generate & Load Held-Out Test Set
```bash
# Generate 300 harder test tickets (50 per category, no resolutions)
python -m scripts.generate_synthetic_data \
  --mode test --count 300 --output data/raw/synthetic_test.csv

# Load as WEBHOOK source (isolated from training)
python -m scripts.load_tickets \
  --input-path data/raw/synthetic_test.csv \
  --ticket-source webhook --source synthetic_test
```

### Train & Index
```bash
python -m scripts.train_classifier
python -m scripts.index_knowledge_base
```

### Start API
```bash
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

### Run Evaluation Suite
```bash
python -m evaluation.run_all \
  --fail-under-f1 0.92 \
  --fail-under-llm 3.5 \
  --fail-latency 5.0 \
  --fail-auto-resolve 25.0 \
  --fail-under-routing 0.75
```

---

## 8. Key Files Reference

### Backend (`backend/`)

| Path | Purpose |
| --- | --- |
| `src/core/config.py` | All settings (Pydantic, reads `.env`) |
| `src/core/logging.py` | Structured JSON logger |
| `src/db/models.py` | SQLAlchemy ORM models |
| `src/db/repositories/` | Async DB repositories (ticket, kb, feedback) |
| `src/ingestion/pipeline.py` | Validation, PII masking, dedup |
| `src/classification/classifier.py` | Embedding + LinearSVC inference |
| `src/rag/retriever.py` | Hybrid RAG retriever (dense + BM25 + MMR) |
| `src/rag/generator.py` | LLM abstraction (Ollama / Claude) |
| `src/agents/` | AutoGen orchestration |
| `src/api/main.py` | FastAPI app entrypoint |
| `scripts/setup_db.py` | Create tables and pgvector extension |
| `scripts/generate_synthetic_data.py` | Claude-powered synthetic ticket generator (train + test modes) |
| `scripts/load_tickets.py` | Synthetic CSV → DB loader (training + held-out test set) |
| `scripts/train_classifier.py` | Train and save LinearSVC (calibrated) model |
| `scripts/index_knowledge_base.py` | Build BM25 index from KB entries |
| `evaluation/classification_eval.py` | Evaluator 1: Macro F1 |
| `evaluation/rag_eval.py` | Evaluator 2: Precision@5 |
| `evaluation/llm_judge.py` | Evaluator 3: LLM-as-judge |
| `evaluation/end_to_end_eval.py` | Evaluator 4: p95 latency |
| `evaluation/routing_accuracy_eval.py` | Evaluator 5: Routing accuracy (held-out set) |
| `evaluation/run_all.py` | Unified runner for all 5 evaluators |
| `data/raw/` | Generated CSV files |
| `data/models/classifier.pkl` | Trained classifier artifact |

### Project Root

| Path | Purpose |
| --- | --- |
| `docs/DATA_LOADING_GUIDE.md` | Step-by-step synthetic data generation and loading guide |
| `docs/IMPLEMENTATION_PLAN.md` | Original architecture and phase plan |
| `docs/API_CONTRACT.md` | REST API endpoint documentation |
| `docs/implementation_phases/Phase_*_Implementation.md` | Per-phase implementation notes |
| `docker/docker-compose.yml` | Full stack container definition |
| `.env` | Environment configuration (not committed) |

---

## 9. Environment Configuration (`.env` key values)

```env
DATABASE_URL=postgresql+asyncpg://saisivakesh:Password123@localhost:5432/ticket_routing
SECRET_KEY=ea994fc7b70122a00075fcc0ca2582bdbef9b4a9855cefc18c33dd31c7c6945b
LLM_BACKEND=ollama                        # or "claude"
ANTHROPIC_API_KEY=                        # required if LLM_BACKEND=claude
CLAUDE_MODEL=claude-haiku-4-5-20251001
OLLAMA_MODEL=mistral:7b-instruct
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
CONFIDENCE_HIGH_THRESHOLD=0.85
CONFIDENCE_LOW_THRESHOLD=0.60
```

---

## 10. Current State (as of 2026-06-08)

| Item | Status |
| --- | --- |
| All 10 phases implemented | ✅ Complete |
| DB schema created (`setup_db`) | ✅ Done |
| Synthetic training data generated & loaded | ⚠️ **Pending** — run steps 1–2 in DATA_LOADING_GUIDE.md |
| Synthetic test set generated & loaded | ⚠️ **Pending** — run steps 3–4 in DATA_LOADING_GUIDE.md |
| Classifier trained | ⚠️ **Pending** — after data load |
| KB indexed | ⚠️ **Pending** — after data load |
| Evaluation suite | ✅ Code complete, ready to run after training |

**Next immediate action:** Follow `DATA_LOADING_GUIDE.md` steps 1 → 4 → 5 → 6 → 8.
