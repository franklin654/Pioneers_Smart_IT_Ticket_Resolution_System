# Implementation Phases (v2)

Same phase count and order as v1 — that build order worked. Each phase below states
what's new/changed vs. v1 (per [`01_LESSONS_LEARNED.md`](01_LESSONS_LEARNED.md)) and
its verification gate.

## Phase 1 — Project Scaffolding & Data Foundation

**Deliverables:** `pyproject.toml`, `core/config.py` (fails closed on missing
`ADMIN_PASSWORD` — audit fix H2), `core/logging.py`, `core/exceptions.py` (incl. new
`ConflictError`), `db/models.py` (incl. `AWAITING_REVIEW` status, structured
`suggested_steps`), repositories, `scripts/setup_db.py` (incl. idempotent
`ALTER TYPE ... ADD VALUE`), `scripts/generate_synthetic_data.py`,
`scripts/load_tickets.py`.

**Gate:** unit + integration tests for all models/repos pass; `setup_db.py` runs
clean against an empty DB.

## Phase 2 — Ingestion Pipeline

**Deliverables:** `ingestion/validator.py`, `pii_masker.py` (Presidio, 8 entity
types, fails loud rather than silently passing through on error — audit fix L6),
`deduplicator.py` (SHA-256 exact + configurable embedding near-dup threshold),
`pipeline.py`.

**Gate:** full unit + integration coverage; p50 latency < 205ms.

## Phase 3 — Embedding & Classification

**Deliverables:** `embedding/generator.py` (`asyncio.to_thread`-wrapped — audit fix
H1), `embedding/store.py`, `classification/trainer.py` (repository-only access —
audit fix H3), `classification/classifier.py`, `classification/confidence.py`
(HIGH/MEDIUM/LOW + multi-domain detection), `scripts/train_classifier.py`.

**Gate:** `classification_eval.py` reports F1 ≥ 0.92 on the held-out set.

## Phase 4 — RAG Pipeline

**Deliverables:** `rag/knowledge_base.py` (pickle I/O wrapped in
`asyncio.to_thread` — audit fix M2), `rag/retriever.py` (70% dense + 30% BM25),
`rag/reranker.py` (MMR, λ=0.7, `asyncio.to_thread`-wrapped), `rag/generator.py`
(`OllamaGenerator` / `ClaudeGenerator` behind one protocol; **prompts the LLM for a
structured JSON step array**, not free markdown text — see
[`03_BACKEND_DESIGN.md`](03_BACKEND_DESIGN.md)).

**Gate:** `rag_eval.py` reports Precision@5 ≥ 0.80.

## Phase 5 — Orchestration & Routing

**Deliverables:** `agents/classifier_agent.py`, `rag_agent.py`, `evaluator_agent.py`
(thin `ConversableAgent` wrappers, no `register_reply`/`_handle_*` dead code — audit
fix C1), `agents/orchestrator.py` (gated pipeline with
`pre_generation_check` → `AWAITING_REVIEW` → `resume_after_reclassification`, per
[`03_BACKEND_DESIGN.md`](03_BACKEND_DESIGN.md)), `routing/router.py` (exposes both
`pre_generation_check` and `decide`), `routing/escalation.py`.

This is the phase with the actual architecture change from v1: the pre-generation
gate and reclassification resume path are net-new, not present in v1 at all.

**Gate:** unit tests cover all 5 router rules independently, plus a test asserting
the RAG agent is **not** invoked when confidence is LOW or `is_multi_domain`; an
integration test drives a ticket through `AWAITING_REVIEW` → reclassify →
terminal status end to end.

## Phase 6 — API Layer

**Deliverables:** `api/main.py`, `api/routes/auth.py` (`/token` **and** `/refresh`
— v1 never built the latter), `api/routes/tickets.py` (incl. `PATCH
/{id}/reclassify`), `api/routes/resolutions.py`, `api/routes/health.py` (Pydantic
response model — audit fix L5), `api/websocket.py`, `api/middleware/auth.py`,
`api/middleware/rate_limiter.py` (checks `X-Forwarded-For` first — audit fix M7),
`api/envelope.py` (standard `data`/`meta`/`error` envelope — `CLAUDE.md` §4.3),
explicit CORS method/header allowlist (audit fix M6).

**Gate:** contract tests against every endpoint's documented shape in
[`05_API_CONTRACT.md`](05_API_CONTRACT.md); auth tests cover valid/expired/wrong-scope
tokens and the refresh rotation path.

## Phase 7 — React Frontend

**Deliverables:** feature-based structure (`features/auth`, `intake`, `resolution`,
`kb`, `agent-sandbox`, `analytics`), typed `api/client.ts` (incl.
`reclassifyTicket`, `refreshAccessToken`), `hooks/useAuth.ts`, `useTickets.ts`,
`useWebSocket.ts`, `shared/` components incl. the new `ReclassifyPanel.tsx`.
a11y attributes and `*.spec.tsx` tests written alongside each component, not after.

**Gate:** `npm run lint` (`tsc --noEmit`) zero errors; Testing Library suite passes;
manual walkthrough of the `AWAITING_REVIEW` → reclassify → resumed pipeline flow.

## Phase 8 — Evaluation Suite

**Deliverables:** `evaluation/classification_eval.py`, `rag_eval.py`,
`llm_judge.py`, `end_to_end_eval.py` (now reports an `awaiting_review` bucket),
`routing_accuracy_eval.py`, `holdout_eval.py` — all six formalized as the baseline
suite from the start (see [`06_DATA_AND_EVALUATION.md`](06_DATA_AND_EVALUATION.md)),
not added piecemeal.

**Gate:** all target metrics from
[`00_PROBLEM_STATEMENT.md`](00_PROBLEM_STATEMENT.md) are met and reported in one
evaluation run.

## Phase 9 — Docker & Monitoring

**Deliverables:** `docker-compose.yml` (postgres, api, frontend, prometheus,
grafana, ollama gpu profile), `docker-compose.dev.yml`, Prometheus metrics
(`tickets_processed_total`, `ticket_processing_duration_seconds`,
`classification_confidence`, `llm_quality_score`, `auto_resolve_rate`, plus a new
`awaiting_review_total` counter), Grafana dashboards.

**Gate:** single `docker compose up` brings the full stack online; Grafana
dashboards render non-empty panels after a handful of test tickets.

## Cross-Phase Discipline

- Every phase ships with its own tests before moving to the next — no "we'll add
  tests later" phase.
- Every audit-fix item from [`03_BACKEND_DESIGN.md` § Audit Fixes](03_BACKEND_DESIGN.md)
  is addressed in the phase that owns the affected file, not deferred to a
  cleanup pass.
- `CLAUDE.md` is the standing contract for every PR in this rebuild — branch
  naming, commit format, layered architecture, and the response envelope apply from
  Phase 1 onward, not retrofitted in Phase 6.
