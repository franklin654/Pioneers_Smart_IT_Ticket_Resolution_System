# API Contract (v2)

Base path: `/api/v1`. All responses use the standard envelope
(`CLAUDE.md` §4.3) — see [`03_BACKEND_DESIGN.md` § Response Envelope](03_BACKEND_DESIGN.md).

## Auth

### `POST /auth/token`

Request (`application/x-www-form-urlencoded`): `username`, `password`.

Response `200`:
```json
{ "data": { "access_token": "...", "token_type": "bearer", "expires_in": 900 } }
```
Sets an `HttpOnly`, `Secure`, `SameSite=Strict` `refresh_token` cookie.

### `POST /auth/refresh` — NEW in v2

No body; reads the `refresh_token` cookie. Response `200`: new access token, same
shape as above. Rotates the refresh cookie. `401` if missing/expired/already-used.

## Tickets

### `POST /tickets/ingest`

Request:
```json
{ "title": "...", "description": "...", "priority": 1, "category": null }
```
`category` optional — omit to let the classifier decide.

Response `202`:
```json
{ "data": { "ticket_id": "...", "status": "new", "message": "Ticket queued for processing" } }
```
`409` with `error.code = "DUPLICATE_TICKET"` and
`error.details = [{ "existing_ticket_id": "...", "duplicate_type": "exact"|"near" }]`
on duplicate detection.

### `GET /tickets/{ticket_id}`

Response `200`:
```json
{
  "data": {
    "id": "...", "title": "...", "description": "...",
    "category": "infrastructure", "priority": 1,
    "status": "awaiting_review",
    "source": "api", "pii_detected": true,
    "created_at": "...", "updated_at": "...",
    "classification": { "predicted_category": "...", "confidence": 0.42, "confidence_level": "low", "is_multi_domain": false, "top_categories": [...] },
    "resolution": {
      "routing_decision": "escalated",
      "suggested_steps": null,
      "escalation_reason": "Low classifier confidence (0.42)",
      "llm_quality_score": null,
      ...
    }
  }
}
```
`404` if not found.

### `GET /tickets/`

Query params:

| Param | Type | Description |
|---|---|---|
| `q` | string (max 200) | Keyword search — ILIKE match on `title` OR `description` |
| `category` | TicketCategory | Filter by category |
| `status` | TicketStatus | Filter by status |
| `priority` | int | Filter by priority (1=High, 2=Med, 3=Low) |
| `offset` | int | Pagination offset (default 0) |
| `limit` | int (max 200) | Page size (default 50) |

Response `200`:
```json
{ "data": [ { "id": "...", "title": "...", "status": "...", ... } ], "meta": { "total": 120, "offset": 0, "limit": 50 } }
```

### `PATCH /tickets/{ticket_id}/reclassify` — NEW in v2

Request:
```json
{ "category": "infrastructure" }
```

Response `202`:
```json
{ "data": { "ticket_id": "...", "status": "classifying" } }
```

Errors:
- `404` — ticket not found.
- `409` (`error.code = "CONFLICT"`) — ticket is not in `awaiting_review` status.
- `422` — invalid category value.

## Resolutions

### `POST /resolutions/{ticket_id}/feedback`

Request:
```json
{ "action": "accepted" | "modified" | "rejected", "modified_resolution": [ { "step_number": 1, "instruction": "..." } ] }
```
`modified_resolution` required (and validated as a non-empty structured step list)
only when `action = "modified"`.

Response: `204 No Content`.

| Action | Ticket status after | Steps updated |
|---|---|---|
| `accepted` | `closed` | No — original steps kept |
| `modified` | `closed` | Yes — `resolutions.suggested_steps` overwritten with submitted steps |
| `rejected` | `escalated` | No |

All actions append a row to `feedback_logs` (audit trail). Modified steps are
persisted to `resolutions.suggested_steps` via a direct SQL UPDATE so the next
`GET /tickets/{id}` returns the corrected steps.

- `404` if no resolution exists yet for this ticket.
- `409` if ticket is not in `auto_resolved` or `assigned` status.

## Knowledge Base

### `GET /kb/`

Semantic search over `knowledge_base_entries` using pgvector ANN (cosine distance).

Query params:

| Param | Type | Description |
|---|---|---|
| `q` | string | Search query. When present, runs sentence-transformer embedding + pgvector ANN. When absent, returns a paginated browse (ILIKE on all text fields). |
| `category` | TicketCategory | Optional category filter applied to both search modes |
| `offset` | int | Pagination offset (browse mode only; semantic results are top-k, not paged) |
| `limit` | int | Max results (default 20) |

Response `200`:
```json
{
  "data": [
    {
      "id": "...",
      "title": "...",
      "description": "...",
      "content": "...",         // full resolution text
      "category": "infrastructure",
      "source_ticket_id": "...",
      "relevance_score": 0.923, // present on semantic results; absent on browse
      "created_at": "..."
    }
  ],
  "meta": { "total": 5, "offset": 0, "limit": 20 }
}
```

## Agent Sandbox

### `POST /sandbox/run`

Runs a ticket description through the full 5-stage pipeline and returns a timed
trace. **No DB writes** — results are ephemeral.

Request:
```json
{ "description": "Cannot access the VPN after password reset", "category": null }
```
`category` optional — if omitted the ClassifierAgent predicts it.

Response `200`:
```json
{
  "data": {
    "ticket_id": "sandbox",
    "traces": [
      {
        "stage": "classifier",
        "duration_ms": 42,
        "result": { "category": "network", "confidence": 0.91, "confidence_level": "high" },
        "info": null
      },
      {
        "stage": "rag",
        "duration_ms": 180,
        "result": { "retrieved_count": 5, "top_titles": ["VPN Setup Guide", ...] }
      },
      { "stage": "reranker", "duration_ms": 35, "result": { "reranked_count": 5 } },
      {
        "stage": "generator",
        "duration_ms": 4200,
        "result": { "steps": [ { "step_number": 1, "instruction": "..." }, ... ] }
      },
      {
        "stage": "evaluator",
        "duration_ms": 3100,
        "result": { "quality_score": 4.2 }
      }
    ],
    "final_status": "auto_resolved"
  }
}
```

The pre-generation confidence gate is **not enforced** in sandbox mode — all 5
stages always run so the full trace is always visible. The ClassifierAgent trace
includes an `info` field indicating whether the gate would have triggered.

`final_status`: `"auto_resolved"` | `"assigned"` | `"escalated"` | `"error"`.

## Health & Metrics

### `GET /health/live`, `GET /health/ready`

Response `200`:
```json
{ "data": { "status": "ok" } }
```

### `GET /metrics`

Prometheus exposition format (not JSON-enveloped — standard for scrape endpoints).

## WebSocket

### `WS /ws/tickets/{ticket_id}`

Server → client events:
```json
{ "event": "status_changed", "status": "retrieving" }
{ "event": "done", "status": "auto_resolved" }
{ "event": "error", "message": "..." }
```

`status_changed` now also fires for the `awaiting_review` transition, so the
frontend updates the queue badge and shows the reclassification panel without a
manual refresh.

## HTTP Status Code Reference

| Situation | Code |
|---|---|
| Successful read | 200 |
| Ticket queued / reclassification accepted | 202 |
| Feedback recorded (no body) | 204 |
| Validation failure | 400 / 422 |
| Unauthenticated | 401 |
| Forbidden | 403 |
| Not found | 404 |
| Duplicate ticket / status conflict | 409 |
| Server error | 500 |
