# TicketIQ — Project Summary
## NASSCOM Hackathon · Trail Blazers Team

**Last updated:** 2026-06-07  
**Working directory:** `app_v2/`  
**Backend root:** `app_v2/backend/`

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
    ├──► [Classifier]  ← LogisticRegression on embeddings
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
| Classifier | scikit-learn LogisticRegression |
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
- `ClassifierService`: loads `data/models/classifier.pkl` (LogisticRegression trained on embedded ticket text)
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

### Phase 10 — Extended Training & Evaluation Data Sources
**Files modified:** `scripts/load_kaggle_data.py`, `src/db/repositories/ticket_repo.py`, `evaluation/run_all.py`, `pyproject.toml`  
**Files created:** `scripts/load_uci_incidents.py`, `scripts/load_servicenow_test_set.py`, `evaluation/routing_accuracy_eval.py`

Goal: expand training data from ~10K to ~100K+ tickets and add a 5th evaluator.

**Key additions:**

1. **`load_kaggle_data.py` extensions**
   - Auto-detects file format by extension: `.csv`, `.json`, `.jsonl`, `.parquet` / `.pq`
   - Elasticsearch export normalisation: detects `_source` column, flattens with `pd.json_normalize()`, strips ES metadata (`_index`, `_type`, `_id`, `_score`) before column detection
   - `--language` filter: drops rows where detected language column doesn't match (e.g. `--language en`)
   - `--source` flag: tags `KnowledgeBaseEntry.source` for traceability
   - Extended column detection candidates:
     - title: `short_description`, `instruction`, `title`, `subject`, `summary`
     - description: `complaint_what_happened`, `body`, `content`, `description`, `text`, `detail`, `document`, `issue`
     - category: `queue`, `assignment_group`, `department`, `category`, `topic_group`, `type`, `class`, `label`, `group`
   - Title fallback: when no title column found, uses first 150 chars of description
   - Text priority handling: maps `"high"` → 1, `"medium"` → 2, `"low"` → 3, `"critical"` → 1
   - Extended `CATEGORY_MAPPING`: added `administrative rights`, `service outages`, `product support`, `network ops`, `internal project`, `purchase`, `outage`, `service outages and maintenance`

2. **`load_uci_incidents.py`** — UCI specialist (ultimately skipped — see dataset analysis below)

3. **`load_servicenow_test_set.py`** — Loads 500-row held-out test set
   - Tags tickets `TicketSource.WEBHOOK` (not CSV) to isolate from training data
   - Does NOT insert into `knowledge_base_entries`
   - Maps `assignment_group` → `TicketCategory` for ground truth

4. **`ticket_repo.get_by_source()`** — new repo method querying by `TicketSource` enum

5. **`routing_accuracy_eval.py`** — 5th evaluator
   - Queries `TicketSource.WEBHOOK` tickets with classification loaded
   - Compares `predicted_category` vs `ticket.category` (ground truth)
   - Per-category accuracy table across all 6 categories
   - Gate: overall accuracy ≥ `fail_under` (default 0.75)

6. **`run_all.py`** updated to run 5/5 evaluators with `--fail-under-routing` CLI option

---

## 4. Key Technical Decisions & Fixes

### Pydantic Settings `extra="ignore"`
Docker Compose env vars (`POSTGRES_DB`, `POSTGRES_USER`, etc.) in the shared `.env` caused `ValidationError: extra key not allowed` on startup. Fixed by adding `extra="ignore"` to `SettingsConfigDict` in `src/core/config.py`.

### Content Hash Deduplication
SHA-256 of `title.strip().lower() + "::" + description.strip().lower()`. A dataset where `issue` (short categorical label like "Billing") was used as both title and description caused near-total deduplication (154 inserted out of 78,313). Fixed by prioritising `complaint_what_happened` as description candidate for that dataset.

### 6StringNinja Dataset — Held-Out Test Set Strategy
Dataset has only 500 rows — too small for training. Repurposed as a held-out routing evaluation set by using `TicketSource.WEBHOOK` as a DB discriminator. No schema changes needed; the `TicketSource` enum value was unused in the hackathon context.

### pgvector IVFFlat Index Tuning
At 82K KB entries, the default `lists=100` becomes suboptimal. Recommended tuning: `lists=200–300` for better recall/performance trade-off.

---

## 5. Dataset Analysis & Loading Pipeline

### Files Present in `app_v2/backend/data/raw/`

| File | Rows | Status | Notes |
| --- | --- | --- | --- |
| `kaggle_customer_support.csv` | 8,469 | **Load** (step 3b) | Ticket Subject/Description/Type/Priority/Resolution all detected ✓ |
| `kaggle_it_service.csv` | 47,837 | **Load** (step 3c) | `Document`→desc, `Topic_group`→category — fixed in Phase 10 analysis |
| `kaggle_parthpatil.csv` | 29,651 | **Load** (step 3d) | `Body`→desc, `Department`→category; text priority fixed |
| `multilingual.csv` | 28,587 | **Load** (step 3e) | Use `--language en` for 16,338 EN rows; all columns detected ✓ |
| `servicenow_test.parquet` | 500 | **Load last** (step 3f) | Held-out test set; `IT Support`→APP, `Network Ops`→NETWORK ✓ |
| `kaggle_automatic.json` | 78,313 | **SKIP** | Financial domain (CFPB complaints); no IT categories; do not load |
| `uci_incidents.csv` | 141,712 | **SKIP** | Fully anonymized ("Category 26", "Symptom 72", "Group 70"); no usable text |
| `bitext.csv` | 26,872 | **SKIP** | E-commerce categories (ORDER/REFUND/INVOICE); no IT labels |

### Datasets Not Downloaded / No Longer Available

| Dataset | Reason |
| --- | --- |
| `kaggle_it_support.csv` (suraj520) | No longer available on Kaggle |

### Effective Training Data Volume

| Source | Rows loaded | IT-labeled |
| --- | --- | --- |
| Synthetic (optional) | ~1,000 | ~1,000 |
| Kaggle Customer Support | ~8,500 | partial |
| Kaggle IT Service | ~47,800 | ~23,000 |
| Kaggle parthpatil | ~29,600 | ~12,000 |
| Multilingual (EN) | ~16,300 | ~12,000 |
| **Total training** | **~103,000** | **~48,000+** |
| 6StringNinja (test set) | 500 | 500 |

---

## 6. Database State & Cleanup

### DB Connection
```
postgresql+asyncpg://saisivakesh:Password123@localhost:5432/ticket_routing
```

### DB Cleanup Required
The Automatic Ticket Classification dataset (`kaggle_automatic.json`) was loaded by mistake during earlier testing — 20,930 tickets with `category=null` were inserted with `source='csv'`. These must be deleted before loading the correct datasets:

```sql
DELETE FROM tickets WHERE source = 'csv';
```

This cascades to all child rows (`ticket_classifications`, `ticket_resolutions`, `ticket_embeddings`, `feedback_logs`) automatically.

### Schema Highlights
- `tickets.content_hash` — SHA-256 dedup key; unique constraint prevents re-inserting identical tickets
- `tickets.source` — `TicketSource` enum; `WEBHOOK` is reserved for the held-out test set
- `knowledge_base_entries.source` — free-text string (e.g. `"kaggle_it_service"`, `"multilingual"`) for traceability
- `knowledge_base_entries.embedding` — `vector(384)` with IVFFlat index

---

## 7. How to Run the Full Pipeline

All commands run from `app_v2/backend/` with the `ticket_routing` conda environment active.

### Setup (once)
```bash
conda activate ticket_routing
pip install -e ".[dev]"
python -m scripts.setup_db
```

### DB Cleanup (if any bad data exists)
```bash
psql postgresql://saisivakesh:Password123@localhost:5432/ticket_routing \
  -c "DELETE FROM tickets WHERE source = 'csv';"
```

### Load Training Data
```bash
# 3b. Customer Support
python -m scripts.load_kaggle_data --input-path data/raw/kaggle_customer_support.csv --source kaggle_customer_support

# 3c. IT Service (~47K, ~23K labeled)
python -m scripts.load_kaggle_data --input-path data/raw/kaggle_it_service.csv --source kaggle_it_service

# 3d. Parthpatil (~29K, ~12K labeled)
python -m scripts.load_kaggle_data --input-path data/raw/kaggle_parthpatil.csv --source kaggle_parthpatil

# 3e. Multilingual EN (~16K, ~12K labeled)
python -m scripts.load_kaggle_data --input-path data/raw/multilingual.csv --language en --source multilingual

# 3f. ServiceNow test set (held-out — load LAST)
python -m scripts.load_servicenow_test_set --input-path data/raw/servicenow_test.parquet
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

### Backend (`app_v2/backend/`)

| Path | Purpose |
| --- | --- |
| `src/core/config.py` | All settings (Pydantic, reads `.env`) |
| `src/core/logging.py` | Structured JSON logger |
| `src/db/models.py` | SQLAlchemy ORM models |
| `src/db/repositories/` | Async DB repositories (ticket, kb, feedback) |
| `src/services/ingestion.py` | Validation, PII masking, dedup |
| `src/services/classifier.py` | Embedding + LogisticRegression inference |
| `src/services/retriever.py` | Hybrid RAG retriever (dense + BM25 + MMR) |
| `src/services/llm.py` | LLM abstraction (Ollama / Claude) |
| `src/agents/` | AutoGen orchestration |
| `src/api/main.py` | FastAPI app entrypoint |
| `scripts/setup_db.py` | Create tables and pgvector extension |
| `scripts/load_kaggle_data.py` | Generic multi-format loader (CSV/JSON/Parquet) |
| `scripts/load_servicenow_test_set.py` | Held-out test set loader |
| `scripts/load_uci_incidents.py` | UCI specialist loader (dataset currently skipped) |
| `scripts/train_classifier.py` | Train and save LogisticRegression model |
| `scripts/index_knowledge_base.py` | Build BM25 index from KB entries |
| `scripts/generate_synthetic_data.py` | Claude-powered synthetic ticket generator |
| `evaluation/classification_eval.py` | Evaluator 1: Macro F1 |
| `evaluation/rag_eval.py` | Evaluator 2: Precision@5 |
| `evaluation/llm_judge.py` | Evaluator 3: LLM-as-judge |
| `evaluation/end_to_end_eval.py` | Evaluator 4: p95 latency |
| `evaluation/routing_accuracy_eval.py` | Evaluator 5: Routing accuracy (held-out set) |
| `evaluation/run_all.py` | Unified runner for all 5 evaluators |
| `data/raw/` | Raw dataset files |
| `data/models/classifier.pkl` | Trained classifier artifact |

### Project Root (`app_v2/`)

| Path | Purpose |
| --- | --- |
| `DATA_LOADING_GUIDE.md` | Step-by-step loading instructions with exact CLI commands |
| `IMPLEMENTATION_PLAN.md` | Original architecture and phase plan |
| `API_CONTRACT.md` | REST API endpoint documentation |
| `imple_docs/Phase_*_Implementation.md` | Per-phase implementation notes |
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

## 10. Current State (as of 2026-06-07)

| Item | Status |
| --- | --- |
| All 10 phases implemented | ✅ Complete |
| DB schema created (`setup_db`) | ✅ Done |
| Bad data cleanup (`DELETE WHERE source='csv'`) | ⚠️ **Pending** — must run before loading |
| Training data loaded | ⚠️ **Pending** — steps 3b–3f |
| Classifier trained | ⚠️ **Pending** — after data load |
| KB indexed | ⚠️ **Pending** — after data load |
| Evaluation suite | ✅ Code complete, ready to run after training |

**Next immediate action:** Run the `DELETE` cleanup command, then follow `DATA_LOADING_GUIDE.md` steps 3b → 3f → 4 → 5 → 7.
