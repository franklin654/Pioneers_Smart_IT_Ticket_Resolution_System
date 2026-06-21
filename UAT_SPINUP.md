# TicketIQ — UAT Spin-Up Guide

> **Branch:** `redesign` · **Stack:** FastAPI 0.115 + PostgreSQL 16 + pgvector + React 19

---

## Section 1 — Prerequisites

### For Path A (Docker — recommended for UAT)

| Tool | Minimum version | Verify |
|---|---|---|
| Docker Engine | 24+ | `docker --version` |
| Docker Compose V2 | 2.20+ | `docker compose version` |
| NVIDIA Container Toolkit | latest | `nvidia-smi` (only if using local Ollama GPU profile) |

**LLM backend — choose one before starting:**
- **Claude API** (recommended for UAT, no GPU needed): have `ANTHROPIC_API_KEY` ready
- **Local Ollama**: have Ollama running locally and `mistral:7b-instruct` pulled, or plan to use the GPU Docker profile

### For Path B (Local dev — hot reload)

| Tool | Minimum version | Verify |
|---|---|---|
| Docker Engine | 24+ | `docker --version` (for Postgres dev container) |
| conda / mamba | latest | `mamba --version` |
| Python | 3.11.x (not 3.12+) | `python --version` |
| Node.js | 20+ | `node --version` |

> **Important**: `pyproject.toml` requires `python>=3.11,<3.12`. Do not use Python 3.12 or later.

---

## Section 2 — Environment Setup

From the project root:

```bash
cp .env.example .env
```

Open `.env` and set:

| Variable | Required | Notes |
|---|---|---|
| `POSTGRES_PASSWORD` | **REQUIRED** | Any strong random string, e.g. `openssl rand -hex 16` |
| `ADMIN_PASSWORD` | **REQUIRED** | Must not be `admin`, `password`, `changeme123`, or any single word. Min 10 chars. |
| `JWT_SECRET_KEY` | **REQUIRED** | Minimum 32 characters. `openssl rand -hex 32` works. |
| `LLM_PROVIDER` | OPTIONAL | `ollama` (default) or `claude` |
| `OLLAMA_BASE_URL` | OPTIONAL | Default `http://ollama:11434`. If running Ollama on your host: `http://host.docker.internal:11434` |
| `ANTHROPIC_API_KEY` | REQUIRED if `LLM_PROVIDER=claude` | Also always required for `generate_synthetic_data.py` regardless of `LLM_PROVIDER` |
| `GRAFANA_PASSWORD` | OPTIONAL | Default `admin` — fine for UAT |

**Minimum working `.env` for UAT with Claude API:**

```dotenv
POSTGRES_PASSWORD=uatpassword123secure
ADMIN_PASSWORD=UATadmin2024!
JWT_SECRET_KEY=uatsecretkeyatleast32characterslong1234
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

**Minimum working `.env` for UAT with external Ollama (running on host):**

```dotenv
POSTGRES_PASSWORD=uatpassword123secure
ADMIN_PASSWORD=UATadmin2024!
JWT_SECRET_KEY=uatsecretkeyatleast32characterslong1234
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
ANTHROPIC_API_KEY=sk-ant-...    # still needed for data generation
```

---

## Section 3 — Path A: Full Docker Stack (recommended for UAT)

### Step 1 — Build and start all services

```bash
docker compose up --build -d
```

With local Ollama on GPU instead:

```bash
docker compose --profile gpu up --build -d
# Then pull the model (first time only):
docker compose exec ollama ollama pull mistral:7b-instruct
```

Wait ~60 seconds for all health checks to pass, then verify:

```bash
docker compose ps
```

Expected output (all services `running (healthy)` or `running`):

```
NAME                    STATUS
ticketiq-postgres-1     running (healthy)
ticketiq-api-1          running (healthy)
ticketiq-frontend-1     running
ticketiq-prometheus-1   running
ticketiq-grafana-1      running
```

If `api` is still starting, wait and recheck — it depends on `postgres` being healthy first.

### Step 2 — Bootstrap the database and data pipeline

These commands run inside the `api` container. Run them **in order**:

```bash
# 1. Create schema, enums, and indexes
docker compose exec api python scripts/setup_db.py
```

```bash
# 2. Generate the training corpus (~1 200 tickets, ~5-10 min, calls Anthropic API)
docker compose exec api python scripts/generate_synthetic_data.py \
    --mode train --count 1200 \
    --output data/raw/synthetic_train.csv
```

```bash
# 3. Generate the held-out test set (~300 harder tickets, ~2-3 min)
docker compose exec api python scripts/generate_synthetic_data.py \
    --mode test --count 300 \
    --output data/raw/synthetic_test.csv
```

```bash
# 4. Load training data into the DB (also seeds knowledge_base_entries)
docker compose exec api python scripts/load_tickets.py \
    --input-path data/raw/synthetic_train.csv \
    --source synthetic_train
```

```bash
# 5. Load the held-out set (webhook source — never used for training)
docker compose exec api python scripts/load_tickets.py \
    --input-path data/raw/synthetic_test.csv \
    --source synthetic_test \
    --ticket-source webhook
```

```bash
# 6. Embed all knowledge base entries with sentence-transformers
docker compose exec api python scripts/embed_knowledge_base.py
```

```bash
# 7. Train the classifier and save data/models/classifier.pkl
docker compose exec api python scripts/train_classifier.py
```

> **Note:** Steps 2 and 3 always call the **Anthropic API** regardless of `LLM_PROVIDER`.
> `ANTHROPIC_API_KEY` must be set in `.env` for these to work.

### Step 3 — Verify services are healthy

```bash
# API liveness
curl http://localhost:8000/api/v1/health/live
# Expected: {"data":{"status":"ok"}}

# API readiness (DB connected)
curl http://localhost:8000/api/v1/health/ready
# Expected: {"data":{"status":"ok","version":"0.1.0"}}

# Prometheus metrics (raw text)
curl http://localhost:8000/api/v1/health/metrics | head -20
```

### Step 4 — Open the application

| Service | URL | Credentials |
|---|---|---|
| **Frontend (main app)** | http://localhost | `admin` / `$ADMIN_PASSWORD` |
| API Swagger docs | http://localhost:8000/api/docs | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | `admin` / `$GRAFANA_PASSWORD` |

---

## Section 4 — Path B: Local Dev (hot reload)

Use this path if you want to edit code and see changes live without rebuilding Docker images.

### Step 1 — Python environment

```bash
mamba create -n ticketiq python=3.11
mamba activate ticketiq
cd backend
pip install -e ".[dev]"
python -m spacy download en_core_web_sm
```

### Step 2 — Start a Postgres dev container

```bash
docker run -d --name ticketiq-postgres \
    -p 5544:5432 \
    -e POSTGRES_USER=ticketiq \
    -e POSTGRES_PASSWORD=ticketiq_dev_pw \
    -e POSTGRES_DB=ticketiq \
    pgvector/pgvector:pg16
```

> If you get a Docker permission error: `sudo usermod -aG docker $USER && newgrp docker`

### Step 3 — Local `.env`

Create `backend/.env`:

```dotenv
DATABASE_URL=postgresql+asyncpg://ticketiq:ticketiq_dev_pw@localhost:5544/ticketiq
ADMIN_PASSWORD=local_dev_admin123
JWT_SECRET_KEY=local_dev_secret_key_at_least_32_characters_x
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
ANTHROPIC_API_KEY=sk-ant-...
```

### Step 4 — Bootstrap (from `backend/` directory, venv active)

```bash
python scripts/setup_db.py

python scripts/generate_synthetic_data.py \
    --mode train --count 1200 \
    --output data/raw/synthetic_train.csv

python scripts/generate_synthetic_data.py \
    --mode test --count 300 \
    --output data/raw/synthetic_test.csv

python scripts/load_tickets.py \
    --input-path data/raw/synthetic_train.csv \
    --source synthetic_train

python scripts/load_tickets.py \
    --input-path data/raw/synthetic_test.csv \
    --source synthetic_test \
    --ticket-source webhook

python scripts/embed_knowledge_base.py
python scripts/train_classifier.py
```

### Step 5 — Start the API

```bash
# From backend/ with venv active
uvicorn src.api.main:app --reload --port 8000
```

### Step 6 — Start the frontend

```bash
# New terminal
cd frontend
npm install
npm run dev
```

### Step 7 — Access points

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API Swagger | http://localhost:8000/api/docs |
| Prometheus metrics | http://localhost:8000/api/v1/health/metrics |

> Grafana and Prometheus are not started in Path B. Run them separately if needed:
> `docker compose up -d prometheus grafana` (from project root, with `.env` present).

---

## Section 5 — UAT Checklist

Log in as `admin` with the `ADMIN_PASSWORD` you set in `.env`.

- [ ] **1. Login**
  - Open the app URL, you should see the login screen.
  - Enter `admin` / your `ADMIN_PASSWORD`. Confirm you land on the main tab shell.

- [ ] **2. Submit a ticket and watch real-time status streaming**
  - Go to **Submit Ticket** tab.
  - Enter a clear, specific title and description for one of the 6 domains (infrastructure, application, security, database, access_management, network).
  - Example: _"Title: Production database server out of disk space | Description: The primary PostgreSQL server on db-prod-01 has run out of disk space and connections are failing."_
  - Submit. Switch to the **Resolution** tab and find the ticket.
  - Watch the status badge update live: `ingesting` → `classifying` → `retrieving` → `generating` → `auto_resolved` / `assigned` / `escalated`.

- [ ] **3. Trigger an AWAITING_REVIEW case**
  - Submit a ticket that spans two domains or uses vague language.
  - Example: _"Title: System issue | Description: Something is wrong with access to the application and the underlying network seems slow too. Users can't log in and the database might also be involved."_
  - The status should become `awaiting_review`. The **Resolution** tab should show the reclassification panel.
  - Pick a category and click **Submit Reclassification**. The pipeline should resume and complete.

- [ ] **4. Review a completed resolution**
  - Find an `auto_resolved` or `assigned` ticket in the Resolution tab.
  - Confirm the resolution steps are displayed as numbered steps (not raw markdown).
  - Confirm the classification category, confidence tier, and routing decision are shown.

- [ ] **5. Knowledge Base search**
  - Go to the **Knowledge Base** tab.
  - Search for a term related to one of the 6 domains (e.g. "disk space", "firewall", "password reset").
  - Confirm results appear with category badges.

- [ ] **6. Agent Sandbox (pipeline trace)**
  - Go to the **Agent Sandbox** tab.
  - Enter a ticket title and description and run the pipeline in trace mode.
  - Confirm per-agent traces (input, output, latency) are visible as expandable sections.

- [ ] **7. Analytics dashboard**
  - Go to the **Analytics** tab.
  - Confirm the status distribution and category distribution charts render and show data.
  - Click **Refresh** — confirm the charts update.

- [ ] **8. Prometheus metrics**
  - Visit http://localhost:8000/api/v1/health/metrics (Docker) or same port in local dev.
  - Confirm you see `ticketiq_tickets_processed_total`, `ticketiq_classification_confidence_bucket`, and other `ticketiq_*` metrics.

- [ ] **9. Grafana dashboard** (Docker path only)
  - Visit http://localhost:3000, log in as `admin` / `$GRAFANA_PASSWORD`.
  - Open the **TicketIQ** dashboard (auto-provisioned).
  - Confirm all 8 panels load and show data after you have processed a few tickets.

---

## Section 6 — Troubleshooting

### `api` container exits immediately

```bash
docker compose logs api --tail=50
```

Common causes:
- **Missing required env var**: look for `ValidationError` in logs. Check `.env` has `POSTGRES_PASSWORD`, `ADMIN_PASSWORD`, and `JWT_SECRET_KEY`.
- **DB not ready**: the `api` depends on `postgres` being `healthy`. Run `docker compose ps` to check postgres status. Wait and retry `docker compose up -d api`.
- **`JWT_SECRET_KEY` too short**: must be ≥ 32 characters.

### `npm run build` fails in Docker

```bash
docker compose build frontend
```

If you see `npm ci` errors, clear the build cache:

```bash
docker compose build --no-cache frontend
```

### pgvector extension missing

```bash
docker compose exec api python -c "
import asyncio
from sqlalchemy import text
from src.db.database import get_engine
async def check():
    async with get_engine().connect() as c:
        r = await c.execute(text(\"SELECT extname FROM pg_extension WHERE extname='vector'\"))
        print(r.fetchall())
asyncio.run(check())
"
```

If empty, the `setup_db.py` script installs it. Re-run:

```bash
docker compose exec api python scripts/setup_db.py
```

If it still fails, the postgres image may not have the extension — confirm you are using `pgvector/pgvector:pg16` (not plain `postgres:16`).

### Classifier not found on API startup

The API loads `data/models/classifier.pkl` lazily (on first ticket ingest). If generation fails with a `FileNotFoundError`:

```bash
docker compose exec api python scripts/train_classifier.py
```

This requires the training data to be loaded first (`load_tickets.py` step).

### Ollama model not pulled

If using `LLM_PROVIDER=ollama` and tickets get stuck at `generating`:

```bash
# GPU profile
docker compose exec ollama ollama pull mistral:7b-instruct

# External Ollama on host
ollama pull mistral:7b-instruct
```

Check that `OLLAMA_BASE_URL` in `.env` is reachable from the api container:

```bash
docker compose exec api curl -s ${OLLAMA_BASE_URL}/api/tags | head -c 200
```

### Port conflicts

Default ports: `80` (frontend), `8000` (API), `5432` (Postgres), `9090` (Prometheus), `3000` (Grafana).

To check what's using a port:

```bash
sudo ss -tlnp | grep ':80 '
```

To change a port, edit `docker-compose.yml` (left side of the `ports` mapping only — never the right side) and restart.

### WebSocket connection failing (status never updates)

In the **Resolution** tab, if the status badge never changes:
- Confirm nginx is running (Docker path): `docker compose ps frontend`
- In the browser console, look for `WS /ws/tickets/...` connection errors
- In Docker, the nginx `/ws/` location proxy handles upgrades — if you see `502`, check `docker compose logs api`

---

## Section 7 — Teardown

### Stop all containers (keep data)

```bash
docker compose down
```

### Stop and remove all data (full reset)

```bash
docker compose down -v
```

This deletes all named volumes: `postgres_data`, `model_data`, `prometheus_data`, `grafana_data`, `ollama_data`. After this you must re-run the full bootstrap pipeline (Section 3, Steps 1–7).

### Remove built images as well

```bash
docker compose down -v --rmi local
```

### Stop local dev (Path B)

```bash
# Stop uvicorn: Ctrl+C in that terminal
# Stop Vite: Ctrl+C in that terminal
# Stop the dev Postgres container:
docker stop ticketiq-postgres && docker rm ticketiq-postgres
```

---

## Quick Reference

```
Ports (Docker/Path A)       Ports (Local/Path B)
──────────────────────       ────────────────────
http://localhost             http://localhost:5173   ← Frontend
http://localhost:8000/api    http://localhost:8000   ← API / Swagger
http://localhost:9090        (start separately)      ← Prometheus
http://localhost:3000        (start separately)      ← Grafana

Login: admin / $ADMIN_PASSWORD (value you set in .env)
```
