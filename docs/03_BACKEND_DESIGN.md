# Backend Design (v2)

Follows the layered architecture and domain-by-feature structure mandated by
[`CLAUDE.md`](../CLAUDE.md) §2–3: `Controller → Service → Repository → Database`,
no layer importing from the layer above it, no business logic in `main.py`.

## Domain Modules

```
src/
  core/            config.py, logging.py, exceptions.py
  db/              models.py, database.py, repositories/
  schemas/          Pydantic v2 request/response schemas (one file per domain)
  ingestion/        validator.py, pii_masker.py, deduplicator.py, pipeline.py
  embedding/        generator.py, store.py
  classification/   classifier.py, trainer.py, confidence.py
  rag/               retriever.py, reranker.py, generator.py, knowledge_base.py
  agents/            classifier_agent.py, rag_agent.py, evaluator_agent.py, orchestrator.py
  routing/           router.py, escalation.py
  api/                routes/, middleware/, websocket.py, dependencies.py
  monitoring/         metrics.py, health.py
```

`main.py` only wires dependencies and starts the app — zero business logic, per
`CLAUDE.md` §2.

## Database Schema

Same six tables as v1 (`tickets`, `ticket_embeddings`, `knowledge_base_entries`,
`classifications`, `resolutions`, `feedback_logs`), with two changes:

### `TicketStatus` — new state

```python
class TicketStatus(str, enum.Enum):
    NEW = "new"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    AWAITING_REVIEW = "awaiting_review"   # NEW — paused pre-generation, needs human category
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    AUTO_RESOLVED = "auto_resolved"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"
    CLOSED = "closed"
    REOPENED = "reopened"
```

`AWAITING_REVIEW` is **not** a terminal status — the pipeline resumes once a human
reclassifies. Only `AUTO_RESOLVED`, `ASSIGNED`, `ESCALATED`, `CLOSED` are terminal.

### `Resolution.suggested_steps` — structured, not free text

v1 stored the LLM's raw markdown response as a single `Text` column and made the
frontend regex-split it into steps (UAT finding KB-05 — sub-bullets got flattened
into separate top-level steps). v2 has the LLM generator return — and the RAG agent
persist — a structured list:

```python
class ResolutionStep(BaseModel):
    step_number: int
    instruction: str

class Resolution(Base):
    ...
    suggested_steps: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    # list[ResolutionStep] serialized; None when no resolution was generated
    # (e.g. AWAITING_REVIEW or a pipeline failure before generation)
```

The LLM prompt template requests a JSON array of steps directly (most local/Claude
models support this reliably with a schema in the system prompt + a regex/json
fallback parser); no client-side markdown parsing is needed at all. This removes an
entire class of "rendering doesn't match the generation format" bugs.

### Migration tooling

v1 had no Alembic — `scripts/setup_db.py` used idempotent `create_all` + raw DDL.
v2 keeps that approach for the MVP timeline, but the new `AWAITING_REVIEW` enum
value must be added via an explicit, idempotent
`ALTER TYPE ticket_status ADD VALUE IF NOT EXISTS 'awaiting_review'` statement
alongside the `create_all` call, since native Postgres enums aren't updated by
`create_all` on an existing database.

## Pipeline Stages

`ClassifierAgent`, `RAGAgent`, `EvaluatorAgent` are `autogen.ConversableAgent`
subclasses — single-purpose wrappers exposing one coroutine each
(`_classify`, `_run_rag`, `_evaluate`). They are **not** wired into `GroupChat` or
`initiate_chat`; `TicketOrchestrator` calls their coroutines directly. This is a
deliberate, documented choice (see [`01_LESSONS_LEARNED.md`](01_LESSONS_LEARNED.md)):
deterministic execution order, full unit-testability, and no extra LLM round-trips
on the latency-critical path.

`TicketRouter` and `EscalationDetector` are **plain Python classes with no LLM
in the loop** — never agents, despite v1's plan implying otherwise. Their rules
must be exact, auditable, and trivially unit-testable.

### `TicketOrchestrator` — the gated pipeline

```python
async def process_ticket(self, ticket_id: uuid.UUID) -> Resolution:
    ticket = await self._ticket_repo.get_by_id(ticket_id)

    # Stage 1: Classification
    await self._ticket_repo.update_status(ticket_id, TicketStatus.CLASSIFYING)
    classification_raw = await self._classifier_agent._classify(...)
    classification_output = self._build_classification_output(classification_raw)

    # Pre-generation gate — NEW in v2
    pre_check = self._router.pre_generation_check(classification_output)
    if pre_check is not None:
        return await self._await_review(ticket_id, pre_check, classification_output)

    # Stages 2-6: RAG → evaluate → route → persist (unchanged from v1)
    return await self._run_from_classification(ticket, ticket_id, classification_raw)


async def resume_after_reclassification(
    self, ticket_id: uuid.UUID, category: TicketCategory
) -> Resolution:
    """Resume a pipeline halted at AWAITING_REVIEW with a human-supplied category."""
    ticket = await self._ticket_repo.get_by_id(ticket_id)
    synthetic_classification = {
        "predicted_category": category.value,
        "confidence": 1.0,
        "confidence_level": "high",
        "top_categories": [{"category": category.value, "probability": 1.0}],
        "is_multi_domain": False,
        "classification_method": "human_reviewer",
    }
    await self._resolution_repo.delete_by_ticket_id(ticket_id)  # discard the pre-gate stub row
    return await self._run_from_classification(ticket, ticket_id, synthetic_classification)
```

`_run_from_classification` is the extracted Stage 2–6 body (RAG → evaluate →
`router.decide()` → escalation-detect → persist `Resolution` → update ticket
status) — shared by both the first-pass pipeline and the reclassification resume,
so there is exactly one code path for "generate and route," not two.

### `TicketRouter` — two entry points, one rule set

```python
class TicketRouter:
    def pre_generation_check(self, classification: ClassificationOutput) -> RoutingResult | None:
        """Rules 1-2 only: multi-domain, low confidence. Returns None if neither matches."""
        ...

    def decide(self, classification: ClassificationOutput, llm_quality_score: float) -> RoutingResult:
        """Full 5-rule cascade for the post-generation call. Delegates rules 1-2 to
        pre_generation_check internally so there's one source of truth."""
        ...
```

| Rule | Condition | Outcome | Stage |
|---|---|---|---|
| 1 | `is_multi_domain = True` | `AWAITING_REVIEW` (pre) | Pre-generation gate |
| 2 | `confidence_level = LOW` | `AWAITING_REVIEW` (pre) | Pre-generation gate |
| 3 | `llm_quality_score < 3.5` | `ESCALATED` (terminal) | Post-generation |
| 4 | `confidence_level = HIGH`, score ≥ 3.5 | `AUTO_RESOLVED` | Post-generation |
| 5 | `confidence_level = MEDIUM`, score ≥ 3.5 | `ASSIGNED` | Post-generation |

## Reclassification Endpoint

```
PATCH /api/v1/tickets/{ticket_id}/reclassify
Body: { "category": "<TicketCategory>" }
```

- 404 if the ticket doesn't exist.
- 409 (`ConflictError`, new exception class) if `ticket.status != AWAITING_REVIEW`.
- On success: `ticket_repo.update_category()` (already exists in v1, reused as-is),
  status → `CLASSIFYING`, commit, schedule
  `run_reclassification_background(ticket_id, category)` exactly like ingestion
  schedules `run_orchestrator_background`.

## Auth

v1 defined `refresh_token_expire_days` in config but never implemented the
endpoint. v2 implements it properly, per `CLAUDE.md` §8.1:

- `POST /auth/token` — username/password → short-lived access token (≤15 min) +
  refresh token set as an `HttpOnly`, `Secure`, `SameSite=Strict` cookie.
- `POST /auth/refresh` — reads the refresh cookie, validates it, issues a new access
  token. Refresh tokens are rotated on use (old one invalidated) to limit replay
  window.
- Every request still validates signature, expiry, `iss`, `aud` on the access token.

## Audit Fixes (v1's 18 findings → v2 disposition)

| ID | v1 issue | v2 fix, baked in from the start |
|---|---|---|
| C1 | Dead `asyncio.run()` in AutoGen `_handle_*` reply handlers | Not built — agents only expose the coroutine methods the orchestrator calls directly; no `register_reply` handlers exist at all. |
| C2 | `await session.delete(obj)` — wrong, `delete()` is sync in SQLAlchemy 2.0 async | `BaseRepository.delete()` calls `self.session.delete(obj)` (no `await`) then `await self.session.flush()`. |
| H1 | CPU-bound classifier/embedding/rerank calls block the event loop | Every ML inference call wrapped in `asyncio.to_thread()` from the first implementation, not retrofitted. |
| H2 | Hardcoded default admin password (`"changeme123"`) | No default — `Settings` validator raises at startup if `ADMIN_PASSWORD` is unset or equals the old placeholder. |
| H3 | Trainer bypasses repository, touches `.session` directly | `TicketRepository.get_training_data()` is the only access path; trainer never imports `select()` directly. |
| M1 | Broad `except Exception` swallowing bugs | Catch specific exception types (`json.JSONDecodeError`, `LLMUnavailableError`, `IOError`) only; unexpected exceptions propagate to the global handler and log at ERROR with stack trace, per `CLAUDE.md` §6. |
| M2 | Blocking pickle I/O in async functions | Wrapped in `asyncio.to_thread()`. |
| M3 | Raw SQL f-string in `knowledge_base_repo` | ORM `select().where()` with conditional filters; no string interpolation into SQL. |
| M4 | Unbounded `get_all_for_bm25()` | Takes a `limit` parameter, default 50,000. |
| M5 | Missing indexes (`category`, `source`, `created_at`) | Indexes declared in the model/DDL from the first migration. |
| M6 | CORS `allow_methods=["*"]`, `allow_headers=["*"]` | Explicit method/header allowlist per `CLAUDE.md` §8.3. |
| M7 | Rate limiter ignores `X-Forwarded-For` | Checks `X-Forwarded-For` first, falls back to socket IP. |
| L1 | Empty `__init__.py` — no stable public API | Each domain package exports its public surface explicitly. |
| L2 | N+1 lazy-load risk in ticket/resolution repos | `selectinload()` used everywhere relations are accessed in a loop. |
| L3 | Orchestrator God class (8 responsibilities) | Split: orchestrator only sequences stages; persistence helpers live in `_run_from_classification`; status transitions delegate to `ticket_repo`. |
| L4 | 85-line `_build_orchestrator()` factory | Broken into smaller `_build_classifier()`, `_build_rag()`, `_build_evaluator()` helpers, composed in one short factory. |
| L5 | Health routes return raw dicts | Pydantic `HealthResponse` model, consistent with every other route. |
| L6 | PII masker silently passes through original text on Presidio failure | Logs at WARN with `extra={"metadata": {...}}` and re-raises as a typed exception if masking is mandatory for the entity types detected; never silently ships unmasked PII. |

## Response Envelope

Per `CLAUDE.md` §4.3, every endpoint returns the standard envelope instead of a bare
Pydantic model:

```json
// Success (single resource)
{ "data": { ... } }
// Success (collection)
{ "data": [...], "meta": { "total": 120, "page": 2, "limit": 20 } }
// Error
{ "error": { "code": "...", "message": "...", "details": [...] } }
```

A thin response wrapper (`api/envelope.py`) and a global exception handler (mapping
every `AppBaseException` subclass to the error envelope) implement this once, not
per-route.

See [`05_API_CONTRACT.md`](05_API_CONTRACT.md) for the full endpoint list with
request/response shapes in this envelope.
