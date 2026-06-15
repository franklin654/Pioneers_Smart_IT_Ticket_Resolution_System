# Pioneers — Smart IT Ticket Resolution System

AI-powered intelligent IT ticket routing & auto-resolution. A FastAPI backend
(classification → RAG → LLM-as-judge → routing) paired with the **TicketIQ**
real-time triage workspace UI.

```
.
├── backend/    FastAPI service (Postgres + pgvector, classifier, RAG, agents)
└── frontend/   TicketIQ UI (React + Vite) + Express BFF that bridges to the backend
```

## Architecture

The frontend is a React/Vite single-page app served by a small Express
backend-for-frontend (`frontend/server.ts`). The BFF runs in one of two modes:

| Mode | When | Behavior |
|------|------|----------|
| **Backend** | `BACKEND_API_URL` is set | Proxies the ticket lifecycle (auth, ingest, list, detail, feedback, live status) to the FastAPI backend and adapts its responses to the UI's shape. |
| **Simulation** | `BACKEND_API_URL` is unset | Self-contained engine (Gemini + heuristic fallback) with an in-memory ticket store — runs with zero backend infrastructure. |

The React UI (`frontend/src/`) is identical to the upstream TicketIQ design and
is never coupled to either mode — all backend translation happens in
`frontend/backendBridge.ts`. Endpoints the FastAPI backend does not provide
(system/config/analytics/knowledge browse/translate) are served locally by the BFF.

See `frontend/INTEGRATION.md` for the full schema-mapping reference.

## Quick start (integrated: UI + Python backend)

**Prerequisites:** Node.js 20+, Python 3.12+, PostgreSQL with the `pgvector`
extension. (Optional) Ollama or an Anthropic API key for LLM resolution
generation — without one, tickets classify and route but escalate instead of
auto-resolving.

### 1. Backend

```bash
cd backend
cp .env  .env          # already present; set DATABASE_URL + ADMIN_PASSWORD
# DATABASE_URL=postgresql+asyncpg://<user>:<pass>@localhost:5432/ticket_routing
python -m venv ../venv && source ../venv/bin/activate   # or reuse existing venv
pip install -r requirements.txt
# Create DB objects + load data (see docs/DATA_LOADING_GUIDE.md):
python scripts/setup_db.py
python scripts/index_knowledge_base.py
uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Backend serves on `http://localhost:8000` (`/docs` for Swagger).

### 2. Frontend

```bash
cd frontend
cp .env.example .env
#   BACKEND_API_URL=http://localhost:8000
#   BACKEND_ADMIN_USERNAME / BACKEND_ADMIN_PASSWORD must match backend/.env
npm install
npm run dev            # http://localhost:3000
```

Open **http://localhost:3000**. The UI authenticates against the BFF, which
authenticates to FastAPI with the service credentials and proxies every ticket
action through.

## Quick start (standalone UI, no backend)

```bash
cd frontend
cp .env.example .env
# comment out / remove BACKEND_API_URL
# (optional) set GEMINI_API_KEY for live LLM; otherwise heuristic fallback
npm install && npm run dev      # http://localhost:3000
```

## Production build

```bash
cd frontend
npm run build      # vite build -> dist/, esbuild server.ts -> dist/server.cjs
npm start          # NODE_ENV=production node dist/server.cjs
```

## Verified

- `npm run build` and `tsc --noEmit` pass clean.
- The bridge was validated live against the FastAPI backend (Postgres + pgvector):
  auth, system, list, detail (classification/resolution/agent-log adaptation),
  ingest → background pipeline → terminal status, feedback (204 / 422), and the
  WebSocket live-status relay.
