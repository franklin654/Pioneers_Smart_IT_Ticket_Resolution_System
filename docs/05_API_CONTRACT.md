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

Query: `category`, `status`, `priority`, `offset`, `limit` (max 200).

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

- `accepted` / `modified` → ticket status → `closed`.
- `rejected` → ticket status unchanged, flagged for manual handling.
- `404` if no resolution exists yet for this ticket.

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
