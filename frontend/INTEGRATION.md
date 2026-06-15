# Frontend ↔ Backend Integration

The TicketIQ UI (`src/`) is the upstream design, unmodified. All coupling to the
Python FastAPI backend lives in the Express BFF:

- `server.ts` — HTTP/WS server + API routes. Each ticket-lifecycle route checks
  `isBridgeEnabled()` and, in backend mode, delegates to `backendBridge.ts`.
- `backendBridge.ts` — proxies to FastAPI and adapts schemas.

## Modes

Set by `BACKEND_API_URL` in `.env` (read lazily, after `dotenv.config()`):

- **set** → backend mode (proxy to FastAPI at that URL)
- **unset** → simulation mode (original self-contained engine)

`GET /api/v1/system` reports the active mode (`"backend"` | `"simulation"`).

## Endpoint routing in backend mode

| UI request | Handled by |
|------------|-----------|
| `POST /api/v1/auth/token` | BFF issues a local JWT for the UI; BFF separately authenticates to FastAPI with `BACKEND_ADMIN_*` creds (cached) |
| `POST /api/v1/tickets/ingest` | → FastAPI `POST /api/v1/tickets/ingest` |
| `GET  /api/v1/tickets` | → FastAPI `GET /api/v1/tickets/` |
| `GET  /api/v1/tickets/:id` | → FastAPI `GET /api/v1/tickets/{id}` |
| `POST /api/v1/resolutions/:id/feedback` | → FastAPI `POST /api/v1/resolutions/{id}/feedback` |
| `GET  /api/v1/analytics` | → FastAPI `GET /api/v1/analytics` (SQL aggregation over real tickets), adapted to KPI/chart shape |
| `GET  /api/v1/knowledge` | → FastAPI `GET /api/v1/knowledge` (real `knowledge_base_entries`, lexical search + category filter), adapted to KB item shape |
| `WS   /ws/tickets/:id` | BFF polls FastAPI status every 2s, relays `status_changed`/`done`/`error` |
| `GET  /api/v1/system`,`/config`, `POST /tickets/:id/translate` | served locally (no FastAPI equivalent) |

## Schema adaptation (FastAPI → UI)

| FastAPI field | UI field | Notes |
|---------------|----------|-------|
| `id` | `ticket_id` + `id` | UI keys on `ticket_id` |
| (derived from status / `resolution.routing_decision`) | `routing_path` | drives escalation banner & list colors |
| `resolution.suggested_steps` (string) | `resolution.resolution_steps` (string[]) | split on newlines, strip numbering/bullets |
| `resolution.retrieved_tickets[].entry_id` | `resolution.sources[].ticket_id` | KB references |
| `resolution.llm_quality_score` (0–5) | `resolution.evaluation{relevance,completeness,actionability,avg,rationale}` | composite score mapped across sub-scores |
| `classification.predicted_category` | `classification.category` (added) | `top_categories`/`confidence` pass through unchanged |
| — | `agent_messages[]` | synthesized from classification/resolution artifacts (FastAPI keeps no transcript) |
| — | `language` / `language_name` | `"en"` / `"English"` (FastAPI is English-only) |

### Request translation (UI → FastAPI)

- `priority`: `critical|high|medium|low` → `1|2|3|4` (FastAPI expects int 1–5).
- `category`: passed through when it matches a `TicketCategory`; empty → omitted
  (let the classifier decide). `source` / `min_confidence_threshold` are dropped
  (not part of the FastAPI ingest contract).

## Failure behavior

In backend mode, if FastAPI is unreachable the BFF returns
`502 BACKEND_UNAVAILABLE`; the WebSocket relay keeps polling (the UI also has a
REST polling fallback). To run without any backend, unset `BACKEND_API_URL`.
