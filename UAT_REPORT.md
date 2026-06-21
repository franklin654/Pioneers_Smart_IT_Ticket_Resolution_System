# TicketIQ v2 — UAT Report

**Branch:** `redesign`  
**Environment:** Docker Compose (local UAT stack)  
**Tester:** Sai Sivakesh  
**Date started:** 2026-06-21

---

## Stack State at UAT Start

| Service | Image | Port | Status |
|---|---|---|---|
| postgres | pgvector/pgvector:pg16 | 5544 | healthy |
| api | ticketiq-api (local build) | 8000 | healthy |
| frontend | ticketiq-frontend (nginx) | 80 | healthy |
| prometheus | prom/prometheus:v2.55.1 | 9090 | up |
| grafana | grafana/grafana:11.3.2 | 3000 | up |

**Data loaded:** 1200 training tickets · 300 held-out (WEBHOOK) · 1199 KB entries embedded  
**Classifier:** trained on 1200 samples, 6 categories, saved to `backend/data/models/classifier.pkl`

---

## Issues Found & Fixed

---

### UAT-001 — SQLAlchemy lazy-load crash on GET /tickets and GET /tickets/{id}

| Field | Detail |
|---|---|
| **Severity** | Critical — blocks Resolution tab, Analytics tab, and all ticket retrieval |
| **Discovered** | UAT session 1 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
`GET /api/v1/tickets/` and `GET /api/v1/tickets/{id}` returned 500 errors when the
response included tickets that had a `Classification` or `Resolution` relationship.
The Intake tab (POST only, no relationship access) worked fine.

**Root cause:**  
`_ticket_dict()` in `backend/src/api/routes/tickets.py` was called *after* the
`async with session_scope()` block closed. Async SQLAlchemy 2.0 disables lazy
loading entirely — even `selectinload`-populated relationship attributes require
an active session to be accessed safely. The session was already closed by the
time `_ticket_dict` accessed `ticket.classification` and `ticket.resolution`,
causing a detached-instance / MissingGreenlet error.

Note: `search()` in `ticket_repo.py` correctly declares `selectinload` for both
relationships (lines 75-78) — the query was fine. The bug was purely the
session-lifecycle mismatch in the route handler.

```python
# BEFORE (broken)
async with session_scope() as session:
    ticket = await repo.get_with_relations(ticket_id)
# ← session closed here

_ticket_dict(ticket)   # accesses ticket.classification → CRASH
```

**Fix applied:**  
Moved `_ticket_dict()` (and the `collection()` call in `list_tickets`) inside the
`async with` block so the session is still open when relationships are accessed.

```python
# AFTER (fixed)
async with session_scope() as session:
    ticket = await repo.get_with_relations(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return ok(_ticket_dict(ticket))   # session still open ✓
```

**Files changed:**  
- `backend/src/api/routes/tickets.py` — `get_ticket()` and `list_tickets()`

---

---

### UAT-002 — API container cannot reach Ollama on host

| Field | Detail |
|---|---|
| **Severity** | Critical — ticket pipeline stalls at LLM generation step |
| **Discovered** | UAT session 1 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
Ticket pipeline hung after retrieval — LLM generation never completed. Ollama was
running on the host but the API container could not connect to it.

**Root cause:**  
Ollama binds to `127.0.0.1` by default. The `.env` had
`OLLAMA_BASE_URL=http://172.17.0.1:11434` (Docker bridge IP), which only works
if Ollama is also listening on that interface. Ollama was not.

**Fix applied:**  
1. Added `extra_hosts: ["host.docker.internal:host-gateway"]` to the `api` service
   in `docker-compose.yml` — this resolves `host.docker.internal` to the host machine
   from inside any container, using Docker's built-in host-gateway mechanism.
2. Updated `.env`: `OLLAMA_BASE_URL=http://host.docker.internal:11434`

Verified from inside the container: `mistral:7b-instruct` is reachable.

**Files changed:**  
- `docker-compose.yml` — added `extra_hosts` to `api` service
- `.env` — updated `OLLAMA_BASE_URL`

---

---

### UAT-003 — HTTP 429 Too Many Requests on all pages

| Field | Detail |
|---|---|
| **Severity** | High — blocks all API interaction during normal UAT browsing |
| **Discovered** | UAT session 1 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
All frontend tabs (Resolution, Analytics, KB) returned 429 errors shortly after
opening. Refreshing the page re-triggered the issue immediately.

**Root cause:**  
The sliding-window rate limiter default (`rate_limit_per_minute = 100`) is sized
for production single-user API clients. The frontend makes several concurrent
requests on every page load (ticket list, counts, KB search), which rapidly
exhausted the 100 req/min quota during UAT browsing.

**Fix applied:**  
Added `RATE_LIMIT_PER_MINUTE: "600"` to the `api` service environment in
`docker-compose.yml`. The limiter reads this at startup via Pydantic Settings.

**Note for production:** 100 req/min is the correct production default. The 600
limit is UAT-only and should not be carried into the production `.env`.

**Files changed:**  
- `docker-compose.yml` — added `RATE_LIMIT_PER_MINUTE: "600"` to api environment

---

---

### UAT-004 — Feedback buttons broken: Accept does nothing, Modify loses state on reload, status never reaches CLOSED

| Field | Detail |
|---|---|
| **Severity** | High — feedback loop non-functional |
| **Discovered** | UAT session 1 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptoms:**
1. Clicking **Accept** made no visible change — buttons stayed on screen
2. Clicking **Modify** hid the buttons but showed no editor; buttons reappeared on page reload
3. After accepting a resolution, ticket status remained `auto_resolved` instead of moving to `closed`

**Root causes:**

*Frontend (1 & 2):*
- Accept/Reject called `sendFeedback()` but never set `feedback.action` in local state, so `!feedback.action` stayed true and buttons kept rendering
- Modify set `feedback.action = "modified"` but never rendered a step editor and never called the API — the buttons only appeared gone until state reset on reload
- No `submitted` flag existed to distinguish "editing" from "submitted" for the Modify flow

*Backend (3):*
- `resolutions.py` set both Accept and Modify to `TicketStatus.AUTO_RESOLVED` (a no-op, since the ticket was already in that state). `CLOSED` was never used despite existing in the enum and `TERMINAL_TICKET_STATUSES`.

**Fixes applied:**

*Backend — `backend/src/api/routes/resolutions.py`:*
- Accept → `TicketStatus.CLOSED`
- Modify → `TicketStatus.CLOSED`
- Reject → `TicketStatus.ESCALATED` (was already correct)

*Frontend — `frontend/src/features/resolution/components/ResolutionTab.tsx`:*
- Added `submitted: boolean` to `FeedbackState`
- Accept/Reject now set `submitted: true` after API success → buttons hide, confirmation shows
- Modify now populates `feedback.modified` with current steps on click and renders an inline textarea editor per step
- "Submit changes" calls `sendFeedback("modified", steps)` and sets `submitted: true` → editor hides, confirmation shows
- Confirmation message reflects the specific action: "ticket closed" for accept/modify, "ticket escalated" for reject

**Files changed:**
- `backend/src/api/routes/resolutions.py`
- `frontend/src/features/resolution/components/ResolutionTab.tsx`

---

---

### UAT-005 — Accept/Reject do not persist ticket status to DB (status stays auto_resolved)

| Field | Detail |
|---|---|
| **Severity** | Critical — feedback is recorded but ticket status never changes in DB |
| **Discovered** | UAT session 1 (2026-06-21), confirmed via direct DB query |
| **Status** | ✅ Fixed |

**Symptom:**  
After clicking **Accept**, the `feedback_logs` table received a new `accepted` row (the
feedback itself was persisted), but the ticket's `status` column remained `auto_resolved`
in the DB. Every reload therefore re-showed the buttons and re-fetched `auto_resolved`
from the server — despite the user accepting multiple times.

**Root cause:**  
`TicketRepository.update_status` used ORM-level attribute mutation:

```python
ticket = await self.get_by_id(ticket_id)   # session.get() → identity map hit
ticket.status = status                      # marks object dirty
await self.session.flush()                  # should generate UPDATE
```

When called after `record_feedback` (which had already flushed a FeedbackLog INSERT in
the same session), `session.get()` returned the already-loaded ticket from the identity
map. In async SQLAlchemy 2.0 this pattern has a subtle race: the identity map object
can be in a partially-expired state after the preceding `flush()`, causing the mutation
to not be tracked as dirty and the subsequent `flush()` to be a silent no-op. The
FeedbackLog INSERT committed; the status UPDATE never reached the DB.

**Fix applied:**  
Replaced ORM mutation with a direct SQL `UPDATE` statement in both `update_status`
and `update_category`. Core SQL `execute()` always sends the statement to the DB
within the current transaction, bypassing identity map state entirely:

```python
stmt = update(Ticket).where(Ticket.id == ticket_id).values(status=status)
await self.session.execute(stmt)
```

Verified: after the fix, submitting `accepted` feedback immediately shows
`status = closed` in the DB.

**Files changed:**  
- `backend/src/db/repositories/ticket_repo.py` — `update_status()` and `update_category()`

---

### UAT-006 — Feedback buttons reappear on reload for already-closed tickets

| Field | Detail |
|---|---|
| **Severity** | High — misleading UI; user can submit feedback again on a ticket that is already closed |
| **Discovered** | UAT session 1 (2026-06-21) — was masking UAT-005; visible as standalone issue after UAT-005 fix |
| **Status** | ✅ Fixed |

**Symptom:**  
After clicking **Accept** and seeing "Resolution accepted — ticket closed.", reloading the
page caused the Accept / Modify / Reject buttons to reappear.

**Root cause:**  
The button render condition was `isTerminal && !feedback.action`. `TERMINAL_STATUSES`
includes `"closed"`, so `isTerminal` was `true` for a closed ticket. On reload,
`feedback.action` resets to `null` (local state) so `!feedback.action` was also `true` →
buttons re-rendered despite the server reporting `status: closed`.

**Fix applied:**  
Introduced an `awaitingFeedback` boolean derived from server state that is only `true`
when `activeTicket.status` is `"auto_resolved"` or `"assigned"`. All three feedback
conditions changed from `isTerminal` → `awaitingFeedback`:

- Buttons block: `awaitingFeedback && !feedback.action`
- Modify editor: `awaitingFeedback && feedback.action === "modified" && !feedback.submitted`
- In-session confirmation: `feedback.submitted`

Added a static server-state banner on reload for closed/escalated tickets:
- `status === "closed"` → "Resolution was accepted — ticket is closed."
- `status === "escalated"` → "Resolution was rejected — ticket escalated for review."

**Files changed:**  
- `frontend/src/features/resolution/components/ResolutionTab.tsx`

---

---

### UAT-007 — Knowledge Base tab returns HTTP 404 (backend route missing)

| Field | Detail |
|---|---|
| **Severity** | High — KB tab entirely non-functional |
| **Discovered** | UAT session 2 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
Every request from the Knowledge Base tab returned `404 Not Found`. Submitting any
query (or leaving it blank) immediately showed an error state.

**Root cause:**  
The frontend `KBTab` component calls `GET /api/v1/kb/`. The backend had no route
registered at that path — `kb.py` was not included in the implementation despite
being planned. `main.py` also had no `include_router` call for it.

**Fix applied:**  
Created `backend/src/api/routes/kb.py` with:
- `GET /api/v1/kb/` — when `q` is non-empty, runs semantic vector search via
  `EmbeddingGenerator.encode_one()` + `KnowledgeBaseRepository.search_similar()` (cosine
  distance ANN). When `q` is blank, falls back to a paginated ILIKE browse via
  `KnowledgeBaseRepository.search()`.
- `_entry_dict()` maps `resolution` column → `content`, `source` → `source_ticket_id`,
  and includes cosine-similarity `relevance_score` (= 1 − distance) on semantic results.
- `EmbeddingGenerator` instantiated as a module-level singleton (cheap: `@lru_cache`
  on `_load_model`).

Added `KnowledgeBaseRepository.search()` (ILIKE on title / description / resolution +
category filter + count + pagination) to `backend/src/db/repositories/knowledge_base_repo.py`.

Registered the router in `backend/src/api/main.py`:
```python
from src.api.routes import auth, health, kb, resolutions, sandbox, tickets
app.include_router(kb.router, prefix=prefix)
```

**Files changed:**  
- `backend/src/api/routes/kb.py` *(new)*
- `backend/src/db/repositories/knowledge_base_repo.py` — added `search()`
- `backend/src/api/main.py` — added `kb` import and `include_router`

---

### UAT-008 — Agent Sandbox tab returns HTTP 404 (backend route missing)

| Field | Detail |
|---|---|
| **Severity** | High — Agent Sandbox tab entirely non-functional |
| **Discovered** | UAT session 2 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
`POST /api/v1/sandbox/run` returned `404 Not Found`. The Agent Sandbox tab existed
in the frontend but the backend had no matching route.

**Root cause:**  
Same implementation gap as UAT-007 — `sandbox.py` was planned but not implemented.

**Fix applied:**  
Created `backend/src/api/routes/sandbox.py` with `POST /api/v1/sandbox/run`:
- Accepts `{ description, category? }` body, runs all 5 pipeline stages with per-stage
  wall-clock timing, and returns a trace array without writing any DB rows.
- Stages: ClassifierAgent → RAGAgent (dense-only retrieval) → MMRReranker →
  LLMGenerator → EvaluatorAgent.
- Classification confidence gate is surfaced as an `info` field in the ClassifierAgent
  trace entry but is **not enforced** in sandbox mode — all 5 stages always run so the
  full trace is always visible.
- Uses dense-only retrieval (no BM25 rebuild per request; BM25 requires a full KB
  table scan which is too expensive per HTTP request).
- Response shape: `{ ticket_id: "sandbox", traces: [...], final_status: "auto_resolved" | "escalated" | "error" }`.

Registered in `backend/src/api/main.py`:
```python
app.include_router(sandbox.router, prefix=prefix)
```

**Files changed:**  
- `backend/src/api/routes/sandbox.py` *(new)*
- `backend/src/api/main.py` — added `sandbox` import and `include_router`

---

### UAT-009 — Modified resolution steps not persisted to DB

| Field | Detail |
|---|---|
| **Severity** | High — Modify action saves audit log but resolution content never updates |
| **Discovered** | UAT session 2 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
After editing and submitting modified steps, the `feedback_logs` table received the
correct row, but `resolutions.suggested_steps` was unchanged. Reloading the Resolution
tab showed the original unmodified steps.

**Root cause:**  
`record_feedback` in `resolutions.py` inserted a `FeedbackLog` with `modified_resolution`
(audit trail) but never updated `resolutions.suggested_steps`. There was no repository
method to do so.

**Fix applied:**  
Added `ResolutionRepository.update_suggested_steps()` in
`backend/src/db/repositories/resolution_repo.py` using a direct SQL `UPDATE`:
```python
stmt = (
    update(Resolution)
    .where(Resolution.id == resolution_id)
    .values(suggested_steps=[s.model_dump() for s in steps])
)
await self.session.execute(stmt)
```

Called it from the `"modified"` branch in `backend/src/api/routes/resolutions.py`
before updating the ticket status:
```python
elif body.action == "modified":
    if body.modified_resolution:
        await resolution_repo.update_suggested_steps(
            ticket.resolution.id, body.modified_resolution
        )
    await ticket_repo.update_status(ticket_id, TicketStatus.CLOSED)
```

**Files changed:**  
- `backend/src/db/repositories/resolution_repo.py` — added `update_suggested_steps()`
- `backend/src/api/routes/resolutions.py` — called it on modify action

---

### UAT-010 — Modify editor missing add/delete step controls

| Field | Detail |
|---|---|
| **Severity** | Medium — editor only allows text edits; cannot restructure steps |
| **Discovered** | UAT session 2 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
The inline Modify editor rendered textareas for each step but had no way to delete
an unwanted step or add a new one.

**Fix applied:**  
Added to `frontend/src/features/resolution/components/ResolutionTab.tsx`:
- **Delete button (✕)** — per row; removes the step and re-numbers remaining steps
  (`step_number = index + 1`).
- **+ Add step button** — appends `{ step_number: steps.length + 1, instruction: "" }`
  to the list.
- Changed `key={step.step_number}` → `key={idx}` in the step map so React correctly
  tracks items after deletion/insertion.

**Files changed:**  
- `frontend/src/features/resolution/components/ResolutionTab.tsx`

---

### UAT-011 — Knowledge Base modal missing; no "View full entry" button

| Field | Detail |
|---|---|
| **Severity** | Medium — KB entries show only truncated description; full resolution content inaccessible |
| **Discovered** | UAT session 2 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
KB search results displayed a card with a short description excerpt. The `resolution`
(full remediation content) was not shown anywhere in the UI.

**Fix applied:**  
Added to `frontend/src/features/kb/components/KBTab.tsx`:
- `KBEntryModal` — inline modal component with Escape key + backdrop click to dismiss,
  focus-trap, full `content` (resolution) text, category badge, relevance score %, date,
  and source ticket ID.
- `selected: KBEntry | null` state.
- **"View full entry →"** button on each card sets `selected` to open the modal.
- `relevance_score?: number` field added to the `KBEntry` interface; cards show a
  `{Math.round(score * 100)}% match` badge when present (semantic results only).

**Files changed:**  
- `frontend/src/features/kb/components/KBTab.tsx`

---

### UAT-012 — Ticket Search tab and cross-tab navigation missing

| Field | Detail |
|---|---|
| **Severity** | Medium — no way to search tickets by keyword or navigate from search to resolution |
| **Discovered** | UAT session 2 (2026-06-21) |
| **Status** | ✅ Fixed |

**Symptom:**  
The nav had no Ticket Search tab. The only way to open a specific ticket in the
Resolution tab was to scroll the sidebar list.

**Fix applied:**

*Backend — `backend/src/api/routes/tickets.py` and `backend/src/db/repositories/ticket_repo.py`:*
- Added `q: str | None` field to `TicketSearchFilters` dataclass.
- Added ILIKE filter in `TicketRepository.search()`: matches `title` OR `description`.
- Exposed `q` as a query param on `GET /api/v1/tickets/` (max 200 chars).

*Frontend:*
- Created `frontend/src/features/tickets/components/TicketSearchTab.tsx` — keyword
  search input, status / category / priority dropdowns, Clear filters button, paginated
  results table (PAGE_SIZE = 20) with Title / Status / Category / Priority / Created /
  Open columns. "Open →" button calls `onOpenTicket(ticketId)`.
- Created `frontend/src/features/tickets/index.ts` — public barrel export.
- Updated `frontend/src/app/routes.tsx` — added "Ticket Search" (🔍) tab entry;
  changed `TabRoute.component` to `ComponentType | null` for tabs rendered with
  injected props.
- Updated `frontend/src/app/App.tsx` — lifted `pendingTicketId` state;
  `handleOpenTicket(id)` sets it and switches to "resolution"; `renderTab()` special-cases
  "tickets" (passes `onOpenTicket`) and "resolution" (passes `initialTicketId`).
- Updated `frontend/src/features/resolution/components/ResolutionTab.tsx` — added
  `initialTicketId?: string | null` prop with a `useEffect` that calls `handleSelect`
  on mount/change to auto-select the incoming ticket.

**Files changed:**  
- `backend/src/db/repositories/ticket_repo.py`
- `backend/src/api/routes/tickets.py`
- `frontend/src/features/tickets/components/TicketSearchTab.tsx` *(new)*
- `frontend/src/features/tickets/index.ts` *(new)*
- `frontend/src/app/routes.tsx`
- `frontend/src/app/App.tsx`
- `frontend/src/features/resolution/components/ResolutionTab.tsx`

---

## Issues Pending / Under Investigation

*None at this time. Section will be updated as testing continues.*

---

## Pre-UAT Fixes (applied before testing began)

These were caught during the Docker spin-up, before any functional testing:

| ID | Issue | Fix |
|---|---|---|
| PRE-001 | `frontend/Dockerfile` used `COPY docker/nginx.conf` but build context was `./frontend` — file unreachable | Changed compose build context to project root; updated COPY paths in Dockerfile |
| PRE-002 | `uvicorn --log-config /dev/null` fails on uvicorn ≥ 0.30 (treats `/dev/null` as an INI file) | Replaced with `--no-access-log` |
| PRE-003 | `scripts/` directory not copied into the API Docker image | Added `COPY scripts/ scripts/` to `backend/Dockerfile` |
| PRE-004 | Postgres port `5432` clashed with local dev container | Remapped to `5544:5432` in `docker-compose.yml` |
| PRE-005 | `model_data` named volume (empty) used for `/app/data` — existing CSVs and trained pkl not visible to container | Replaced with bind mount `./backend/data:/app/data` |
| PRE-006 | `README.md` used `--train`/`--test` flags for `load_tickets.py` — flags don't exist | Corrected to `--input-path`, `--source`, `--ticket-source` (two separate invocations) |
| PRE-007 | Frontend `Category` type had `"software"` and `"hardware"` — not valid backend enum values | Corrected to `"application"` and `"database"` in `types.ts` and `constants.ts` |

---

## UAT Checklist Progress

| # | Flow | Status | Notes |
|---|---|---|---|
| 1 | Login (admin credentials) | — | |
| 2 | Submit ticket (Intake tab) + watch status stream | — | |
| 3 | Trigger AWAITING_REVIEW + reclassify | — | |
| 4 | Resolution tab — view completed ticket | — | |
| 5 | Resolution tab — Accept feedback → status closes in DB + banner on reload | — | |
| 6 | Resolution tab — Modify feedback → edit/add/delete steps → submit → steps persisted | — | |
| 7 | Resolution tab — Reject feedback → ticket escalated in DB + banner on reload | — | |
| 8 | Ticket Search tab — keyword search + filters + pagination | — | |
| 9 | Ticket Search tab — "Open →" navigates to Resolution tab with ticket pre-selected | — | |
| 10 | Knowledge Base tab — semantic search returns ranked results with relevance score | — | |
| 11 | Knowledge Base tab — "View full entry →" opens modal with full resolution content | — | |
| 12 | Agent Sandbox tab — pipeline trace runs all 5 stages with timing | — | |
| 13 | Analytics tab — status + category charts | — | |
| 14 | Prometheus metrics endpoint | — | |
| 15 | Grafana dashboard | — | |

*Legend: — not yet tested · ✅ passed · ❌ failed · ⚠️ partial*
