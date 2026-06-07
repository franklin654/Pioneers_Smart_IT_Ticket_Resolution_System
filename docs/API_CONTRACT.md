# API Contract — TicketIQ

**AI-Powered Intelligent Ticket Routing & Resolution Agent**
NASSCOM Hackathon — Trail Blazers

**Base URL:** `http://localhost:8000`
**API prefix:** `/api/v1`
**OpenAPI / Swagger UI:** `http://localhost:8000/docs`
**ReDoc:** `http://localhost:8000/redoc`

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Error Format](#2-error-format)
3. [Rate Limiting](#3-rate-limiting)
4. [Enumerations](#4-enumerations)
5. [Endpoints](#5-endpoints)
   - [Health](#51-health)
   - [Auth](#52-auth)
   - [Tickets](#53-tickets)
   - [Resolutions](#54-resolutions)
6. [WebSocket](#6-websocket)
7. [Schema Reference](#7-schema-reference)
8. [End-to-End Flow](#8-end-to-end-flow)

---

## 1. Authentication

The API uses **JWT Bearer tokens** (HS256).

### Getting a token

```
POST /api/v1/auth/token
Content-Type: application/x-www-form-urlencoded

username=admin&password=changeme123
```

> **Important:** The login endpoint accepts **form data** (`application/x-www-form-urlencoded`), not JSON. This is the OAuth2 Password Flow — the Swagger UI Authorize button handles it automatically.

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### Using the token

Include the token in the `Authorization` header on all protected requests:

```
Authorization: Bearer <access_token>
```

### Token payload (JWT claims)

```json
{
  "sub": "admin",
  "role": "admin",
  "exp": 1234567890
}
```

### Which endpoints require auth?

| Endpoint | Auth Required |
|---|---|
| `POST /api/v1/auth/token` | No |
| `GET /health/*` | No |
| `GET /api/v1/tickets/` | No |
| `GET /api/v1/tickets/{id}` | No |
| `POST /api/v1/tickets/ingest` | **Yes** |
| `POST /api/v1/resolutions/{id}/feedback` | **Yes** |
| `WS /ws/tickets/{id}` | No |

---

## 2. Error Format

All errors — validation, auth, not found, rate limit, server — return the same JSON shape:

```json
{
  "error_code": "TICKET_NOT_FOUND",
  "message": "Ticket 'abc-123' not found",
  "detail": {
    "ticket_id": "abc-123"
  }
}
```

| Field | Type | Description |
|---|---|---|
| `error_code` | `string` | Machine-readable constant (see table below) |
| `message` | `string` | Human-readable description |
| `detail` | `object` | Structured context — contents vary by error type |

### Error codes

| HTTP Status | `error_code` | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Request body fails field constraints |
| 401 | `AUTHENTICATION_ERROR` | Missing, expired, or invalid JWT |
| 403 | `AUTHORIZATION_ERROR` | Valid JWT but insufficient role |
| 404 | `TICKET_NOT_FOUND` | Ticket UUID does not exist |
| 409 | `DUPLICATE_TICKET` | Exact or near-duplicate ticket detected |
| 422 | _(FastAPI default)_ | Pydantic schema validation error |
| 429 | `RATE_LIMIT_EXCEEDED` | Too many requests |
| 500 | `CLASSIFICATION_ERROR` | Classifier failed |
| 500 | `EMBEDDING_ERROR` | Embedding model failed |
| 500 | `RAG_RETRIEVAL_ERROR` | RAG pipeline error |
| 500 | `KNOWLEDGE_BASE_ERROR` | Knowledge base operation failed |
| 503 | `LLM_UNAVAILABLE` | LLM backend (Ollama / Claude) unreachable |

### `detail` contents by error type

**`DUPLICATE_TICKET` (409):**
```json
{
  "existing_ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "duplicate_type": "exact"
}
```
`duplicate_type` is either `"exact"` (MD5 hash match) or `"near"` (embedding similarity ≥ 0.95).

**`RATE_LIMIT_EXCEEDED` (429):**
```json
{
  "retry_after_seconds": 42
}
```

**`TICKET_NOT_FOUND` (404):**
```json
{
  "ticket_id": "abc-123"
}
```

**`LLM_UNAVAILABLE` (503):**
```json
{
  "backend": "ollama",
  "reason": "connection refused"
}
```

---

## 3. Rate Limiting

- **Limit:** 100 requests per 60-second sliding window, per IP address.
- **Exempt:** All `/health/*` endpoints are never rate-limited.
- On limit breach, the API returns HTTP `429` with `retry_after_seconds` in the `detail` field.

---

## 4. Enumerations

### `TicketCategory`

| Value | Label |
|---|---|
| `infrastructure` | Infrastructure |
| `application` | Application |
| `security` | Security |
| `database` | Database |
| `access_management` | Access Management |
| `network` | Network |

### `TicketStatus`

| Value | Terminal? | Meaning |
|---|---|---|
| `new` | No | Just ingested, awaiting processing |
| `classifying` | No | Classifier is running |
| `classified` | No | Category assigned |
| `retrieving` | No | RAG retriever fetching similar tickets |
| `generating` | No | LLM generating resolution |
| `evaluating` | No | Evaluator scoring the resolution |
| `auto_resolved` | **Yes** | High-confidence auto-resolution accepted |
| `assigned` | **Yes** | Assigned to a department queue |
| `escalated` | **Yes** | Escalated to human review |
| `closed` | **Yes** | Manually closed |
| `reopened` | No | Reopened after closure |

### `ConfidenceLevel`

| Value | Confidence range |
|---|---|
| `high` | ≥ 0.85 |
| `medium` | 0.60 – 0.85 |
| `low` | < 0.60 |

### `RoutingDecision`

| Value | Meaning |
|---|---|
| `auto_resolved` | LLM quality score ≥ 3.5, high confidence |
| `assigned` | Routed to department queue |
| `escalated` | Requires human intervention |

### `FeedbackAction`

| Value | Meaning |
|---|---|
| `accepted` | Agent used the suggestion as-is |
| `modified` | Agent edited the suggestion (`modified_resolution` required) |
| `rejected` | Agent discarded the suggestion |

### Priority levels

| Value | Label |
|---|---|
| `1` | Critical |
| `2` | High |
| `3` | Medium |
| `4` | Low |
| `5` | Informational |

### `TicketSource`

| Value | Meaning |
|---|---|
| `api` | Submitted via REST API |
| `csv` | Loaded from Kaggle CSV dataset |
| `webhook` | Received via webhook |

### Department queues (category → department)

| Category | Department |
|---|---|
| `infrastructure` | infra-team |
| `application` | app-team |
| `security` | security-team |
| `database` | db-team |
| `access_management` | iam-team |
| `network` | network-team |

---

## 5. Endpoints

---

### 5.1 Health

#### `GET /health/live`

Liveness probe. Always returns `200` if the process is running. No auth required, not rate-limited.

**Response `200 OK`:**
```json
{ "status": "ok" }
```

---

#### `GET /health/ready`

Readiness probe. Returns `200` only if the database is reachable.

**Response `200 OK`:**
```json
{ "status": "ready", "database": "ok" }
```

**Response `503 Service Unavailable`:**
```json
{ "detail": "Database unavailable" }
```

---

### 5.2 Auth

#### `POST /api/v1/auth/token`

Exchange credentials for a JWT access token.

**Request:**
```
Content-Type: application/x-www-form-urlencoded

username=admin&password=changeme123
```

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors:**

| Status | `error_code` | Cause |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Wrong username or password |

---

### 5.3 Tickets

#### `POST /api/v1/tickets/ingest` 🔒

Submit a new IT support ticket. Processing (classification, RAG, routing) runs asynchronously — the response returns immediately with `202 Accepted`.

**Request body (JSON):**

```json
{
  "title": "VPN authentication failure",
  "description": "Users cannot connect to the corporate VPN from home networks since 09:00 this morning. Affects approximately 30 users in the London office.",
  "priority": 2,
  "category": null
}
```

| Field | Type | Required | Constraints |
|---|---|---|---|
| `title` | `string` | Yes | 3–200 characters; whitespace normalized |
| `description` | `string` | Yes | 10–5000 characters; whitespace normalized |
| `priority` | `integer` | Yes | 1–5 (1 = Critical, 5 = Informational) |
| `category` | `string \| null` | No | One of the `TicketCategory` enum values; omit to let the classifier decide |

**Response `202 Accepted`:**
```json
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "new",
  "message": "Ticket received and queued for processing."
}
```

**Errors:**

| Status | `error_code` | Cause |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Missing or invalid JWT |
| 409 | `DUPLICATE_TICKET` | Exact or near-duplicate already exists |
| 422 | _(Pydantic)_ | Field constraint violated (title too short, priority out of range, etc.) |
| 429 | `RATE_LIMIT_EXCEEDED` | Rate limit hit |

---

#### `GET /api/v1/tickets/{ticket_id}`

Fetch full ticket detail including nested classification and resolution results.

`classification` and `resolution` are `null` while the ticket is still being processed. Poll this endpoint or use the WebSocket to detect when they become populated.

**Path parameter:**

| Parameter | Type | Description |
|---|---|---|
| `ticket_id` | `UUID` | The `ticket_id` returned by `POST /ingest` |

**Response `200 OK`:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "VPN authentication failure",
  "description": "Users cannot connect to the corporate VPN...",
  "category": "network",
  "priority": 2,
  "status": "auto_resolved",
  "source": "api",
  "pii_detected": false,
  "created_at": "2026-06-04T10:23:00Z",
  "updated_at": "2026-06-04T10:23:08Z",
  "classification": {
    "predicted_category": "network",
    "confidence": 0.921,
    "confidence_level": "high",
    "top_categories": [
      { "category": "network",         "probability": 0.921 },
      { "category": "infrastructure",  "probability": 0.054 },
      { "category": "security",        "probability": 0.025 }
    ],
    "is_multi_domain": false,
    "classification_method": "linearsvc_v20260608_143012"
  },
  "resolution": {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "suggested_steps": "1. Check VPN concentrator logs...\n2. Verify firewall rules...",
    "retrieved_tickets": [
      {
        "ticket_id": "ref-ticket-001",
        "title": "VPN disconnection issue Q3",
        "similarity_score": 0.89
      }
    ],
    "llm_quality_score": 4.2,
    "routing_decision": "auto_resolved",
    "assigned_department": null,
    "escalation_reason": null,
    "is_repeated_issue": false
  }
}
```

**Errors:**

| Status | `error_code` | Cause |
|---|---|---|
| 404 | `TICKET_NOT_FOUND` | No ticket with this UUID |

---

#### `GET /api/v1/tickets/`

Paginated list of tickets with optional filters.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `category` | `TicketCategory` | — | Filter by category |
| `status` | `TicketStatus` | — | Filter by status |
| `priority` | `integer (1–5)` | — | Filter by priority |
| `offset` | `integer ≥ 0` | `0` | Records to skip |
| `limit` | `integer 1–200` | `50` | Max records to return |

**Example:**
```
GET /api/v1/tickets/?status=escalated&priority=1&limit=20&offset=0
```

**Response `200 OK`:**
```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "VPN authentication failure",
      "category": "network",
      "priority": 2,
      "status": "auto_resolved",
      "created_at": "2026-06-04T10:23:00Z"
    }
  ],
  "total": 142,
  "offset": 0,
  "limit": 50
}
```

**Errors:**

| Status | Cause |
|---|---|
| 422 | `limit` > 200 or invalid enum value for `category`/`status` |

---

### 5.4 Resolutions

#### `POST /api/v1/resolutions/{ticket_id}/feedback` 🔒

Submit an agent's feedback on a resolution suggestion. Returns `204 No Content` on success.

This endpoint feeds the knowledge base — `MODIFIED` resolutions are candidates for future RAG retrieval.

**Path parameter:**

| Parameter | Type | Description |
|---|---|---|
| `ticket_id` | `UUID` | The ticket whose resolution is being reviewed |

**Request body (JSON):**

```json
{
  "action": "modified",
  "modified_resolution": "Corrected step 3: restart the VPN client instead of reinstalling it."
}
```

| Field | Type | Required | Constraints |
|---|---|---|---|
| `action` | `FeedbackAction` | Yes | `accepted`, `modified`, or `rejected` |
| `modified_resolution` | `string \| null` | Conditional | **Required** when `action` is `modified`; ignored otherwise |

**Response `204 No Content`** — empty body.

**Errors:**

| Status | `error_code` | Cause |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Missing or invalid JWT |
| 404 | `TICKET_NOT_FOUND` | No resolution exists for this ticket yet (still processing) |
| 422 | _(Pydantic)_ | `action` is `modified` but `modified_resolution` is absent or empty |

---

## 6. WebSocket

### `WS /ws/tickets/{ticket_id}`

Stream live status updates for a ticket as it progresses through the processing pipeline.

**No authentication required.** Connect immediately after calling `POST /ingest`.

**Connection:**
```
ws://localhost:8000/ws/tickets/550e8400-e29b-41d4-a716-446655440000
```

**Behavior:**
- The server sends the current status immediately on connect.
- It polls the database every **2 seconds** and emits a `status_changed` event only when the status actually changes.
- When a terminal status is reached, it sends a `done` event and closes the connection cleanly.
- If the ticket is not found, it sends an `error` event and closes.

### Event types

All events are JSON objects.

#### `status_changed`

Emitted whenever the ticket status transitions to a new value.

```json
{
  "event": "status_changed",
  "status": "classifying"
}
```

#### `done`

Emitted once when a terminal status is reached. After this event the connection closes.

```json
{
  "event": "done",
  "status": "auto_resolved"
}
```

Terminal statuses: `auto_resolved`, `assigned`, `escalated`, `closed`.

#### `error`

Emitted when the ticket is not found or an internal error occurs. Connection closes after this event.

```json
{
  "event": "error",
  "message": "Ticket '550e8400-...' not found"
}
```

### Recommended client pattern

```javascript
const ws = new WebSocket(`ws://localhost:8000/ws/tickets/${ticketId}`);

ws.onmessage = (msg) => {
  const event = JSON.parse(msg.data);

  if (event.event === 'status_changed') {
    updateStatusUI(event.status);
  } else if (event.event === 'done') {
    updateStatusUI(event.status);
    fetchFullTicket(ticketId);   // hydrate classification + resolution
    ws.close();
  } else if (event.event === 'error') {
    showError(event.message);
  }
};

ws.onerror = () => showError('WebSocket connection lost');
```

---

## 7. Schema Reference

### `TicketIngestRequest`

```
title           string      3–200 chars (whitespace normalized)
description     string      10–5000 chars (whitespace normalized)
priority        integer     1–5
category        string|null TicketCategory enum, optional (classifier auto-assigns if omitted)
```

### `TicketIngestResponse`

```
ticket_id       UUID        Unique ticket identifier
status          string      Always "new" on ingest
message         string      Human-readable confirmation
```

### `TicketSummary` _(used in list responses)_

```
id              UUID
title           string
category        string|null TicketCategory
priority        integer     1–5
status          string      TicketStatus
created_at      datetime    ISO 8601 (UTC)
```

### `TicketDetailResponse`

```
id              UUID
title           string
description     string
category        string|null TicketCategory
priority        integer     1–5
status          string      TicketStatus
source          string      TicketSource ("api" | "csv" | "webhook")
pii_detected    boolean     True if PII was detected and masked in the description
created_at      datetime    ISO 8601 (UTC)
updated_at      datetime    ISO 8601 (UTC)
classification  object|null ClassificationResponse (null while processing)
resolution      object|null ResolutionResponse (null while processing)
```

### `ClassificationResponse`

```
predicted_category      string      TicketCategory
confidence              float       0.0–1.0 (probability for the top category)
confidence_level        string      "high" | "medium" | "low"
top_categories          array       List of CategoryProbability (top 3)
  └─ category           string      TicketCategory
  └─ probability        float       0.0–1.0
is_multi_domain         boolean     True if top-2 difference < threshold → should escalate
classification_method   string      Model identifier, e.g. "linearsvc_v20260608_143012"
```

### `ResolutionResponse`

```
id                  UUID
suggested_steps     string|null     LLM-generated resolution steps (null if escalated before generation)
retrieved_tickets   array|null      Similar knowledge base entries used for RAG
  └─ ticket_id      string          Reference ticket identifier
  └─ title          string          Reference ticket title
  └─ similarity_score float         0.0–1.0 (cosine similarity)
llm_quality_score   float|null      0.0–5.0 composite judge score (null if not generated)
routing_decision    string          RoutingDecision enum
assigned_department string|null     Department queue (set when routing_decision is "assigned")
escalation_reason   string|null     Human-readable reason (set when routing_decision is "escalated")
is_repeated_issue   boolean         True if a similar ticket appeared in the past 30 days
```

### `PaginatedTicketsResponse`

```
items       array       List of TicketSummary
total       integer     Total matching records (before pagination)
offset      integer     Records skipped
limit       integer     Max records per page
```

### `FeedbackRequest`

```
action                  string          "accepted" | "modified" | "rejected"
modified_resolution     string|null     Required when action = "modified"
```

### `TokenResponse`

```
access_token    string      JWT bearer token
token_type      string      Always "bearer"
```

---

## 8. End-to-End Flow

```
1.  POST /api/v1/auth/token          → get JWT
2.  POST /api/v1/tickets/ingest      → 202, receive ticket_id
3.  WS  /ws/tickets/{ticket_id}      → connect, receive live status events
        status_changed: "classifying"
        status_changed: "classified"
        status_changed: "retrieving"
        status_changed: "generating"
        status_changed: "evaluating"
        status_changed: "auto_resolved"
        done: "auto_resolved"        → close WebSocket
4.  GET /api/v1/tickets/{ticket_id}  → fetch full detail with classification + resolution
5.  POST /api/v1/resolutions/{ticket_id}/feedback  → submit agent feedback (optional)
```

### CORS

The API allows cross-origin requests from `http://localhost:4200` (Angular dev server) and `http://localhost:3000` by default. The `cors_origins` list is configured via the `CORS_ORIGINS` environment variable.

---

*Generated from Phase 6 implementation — `app_v2/backend/src/api/` and `app_v2/backend/src/schemas/`.*
