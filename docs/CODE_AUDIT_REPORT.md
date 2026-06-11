# Code Quality Audit Report — `app_v2/backend/`

> **Date:** 2026-06-07  
> **Scope:** Full read-only audit of `src/`, `scripts/`, `evaluation/`  
> **Purpose:** Identify issues across 5 quality areas before production hardening

---

## Overall Assessment

| Area | Score | Notes |
|------|-------|-------|
| Module Boundaries | ✅ Good | Clean DAG, no circular imports, no wildcard imports |
| Inter-Module Communication | ⚠️ Issues | `asyncio.run()` in dead sync handlers; CPU-bound calls blocking live event loop |
| Database & Data Isolation | ⚠️ Issues | 1 critical bug in base_repo; trainer bypasses repo abstraction |
| Dependency Management | ✅ Good | Unidirectional deps; `_build_orchestrator()` is a code smell but not a blocker |
| Code Structure & Cohesion | ⚠️ Issues | Orchestrator is a God class; empty `__init__.py` = no stable public API |

---

## 🔴 Critical Issues

### C1 — `asyncio.run()` in AutoGen Reply Handlers (Dead Code, Latent Bug)
**Files:**
- `src/agents/classifier_agent.py:94` — `_handle_classify()` calls `asyncio.run(self._classify(msg))`
- `src/agents/rag_agent.py:107` — `_handle_rag()` calls `asyncio.run(self._run_rag(msg))`
- `src/agents/evaluator_agent.py:105` — `_handle_evaluate()` calls `asyncio.run(self._evaluate(msg))`

**Current status:** The orchestrator (`orchestrator.py`) bypasses AutoGen's message-passing protocol entirely — it calls `_classify()`, `_run_rag()`, and `_evaluate()` directly as coroutines. The `_handle_*` sync handlers are dead code. They would crash with `RuntimeError: asyncio.run() cannot be called from a running event loop` if AutoGen's `initiate_chat` were ever used, because the sessions are tied to the main event loop.

**Fix:** Remove the dead `_handle_*` methods and `register_reply` calls from all three agents.

---

### C2 — `await session.delete()` — Incorrect Async Call
**File:** `src/db/repositories/base_repo.py:82`

`session.delete(obj)` is synchronous in SQLAlchemy 2.0's async API. Calling `await` on it returns `None` immediately (or raises `TypeError`) — the object is never scheduled for deletion. Currently dormant because no delete endpoints are exercised in the demo flow.

```python
# WRONG (line 82):
await self.session.delete(obj)

# Correct:
self.session.delete(obj)
await self.session.flush()
```

---

## 🟠 High Severity

### H1 — CPU-Bound ML Inference Blocking the Async Event Loop
**Live codepath — affects every ticket processed:**
- `src/agents/classifier_agent.py:104` — `self._classifier.predict(...)` (sklearn LinearSVC)
- `src/agents/rag_agent.py:123` — `self._embedding_generator.encode_single(...)` (sentence-transformers)
- `src/agents/rag_agent.py:138` — `self._reranker.rerank(...)` (numpy cosine similarity)

These are CPU-bound operations (10–200ms each) running directly inside async functions, blocking all other coroutines during inference. Under concurrent load this starves the server.

**Fix:** Wrap with `asyncio.to_thread()`:
```python
output = await asyncio.to_thread(self._classifier.predict, f"{title} {description}")
query_vector = await asyncio.to_thread(self._embedding_generator.encode_single, query_text)
reranked = await asyncio.to_thread(self._reranker.rerank, candidates)
```

---

### H2 — Hardcoded Default Admin Password
**File:** `src/core/config.py:92`

```python
admin_password: str = "changeme123"
```

Any deployment that forgets to set `ADMIN_PASSWORD` in `.env` is silently insecure. The default is committed to source.

**Fix:** Remove the default; add a `@field_validator` that raises if the value equals `"changeme123"` or is absent.

---

### H3 — Trainer Bypasses Repository Abstraction
**File:** `src/classification/trainer.py` (~line 234)

```python
result = await self._ticket_repo.session.execute(
    select(Ticket).where(...).limit(200_000)
)
```

Accesses `.session` directly on the repo, bypassing the repository interface and coupling trainer to SQLAlchemy internals.

**Fix:** Add `get_training_data(limit: int = 200_000) -> list[Ticket]` to `TicketRepository`.

---

## 🟡 Medium Severity (Technical Debt)

### M1 — Broad `except Exception` Masks Bugs
- `src/agents/orchestrator.py:213` — `_extract_last_reply()` (dead in current flow)
- `src/agents/evaluator_agent.py:125` — falls back to `quality_score = 0.0`
- `src/rag/knowledge_base.py:85-89` — silently rebuilds BM25 on any error

Only specific exceptions (json.JSONDecodeError, LLMUnavailableError, IOError) should be caught.

---

### M2 — Blocking File I/O in Async Functions
**File:** `src/rag/knowledge_base.py:76,104`

`open()` + `pickle.load()` / `pickle.dump()` inside async functions.  
**Fix:** Wrap with `asyncio.to_thread()`.

---

### M3 — Raw SQL f-string in knowledge_base_repo
**File:** `src/db/repositories/knowledge_base_repo.py:107-119`

```python
where_clause = "WHERE kbe.category = :category"
result = await self.session.execute(text(f"SELECT ... {where_clause} ..."), params)
```

Currently safe (no user input) but anti-pattern. Future dev who adds user input creates SQL injection.  
**Fix:** Use ORM `select().where()` with conditional filter.

---

### M4 — Unbounded `get_all_for_bm25()` Loads Entire KB into Memory
**File:** `src/db/repositories/knowledge_base_repo.py:48-58`

No LIMIT — will OOM at scale.  
**Fix:** Add `limit` parameter (default 50,000).

---

### M5 — Missing Database Indexes
Frequent filter columns without indexes: `category` on `knowledge_base_entries`, `source` on `tickets`, `created_at` on `tickets`.

---

### M6 — CORS Allows All Methods and Headers
**File:** `src/api/main.py:81-87` — `allow_methods=["*"]`, `allow_headers=["*"]`

---

### M7 — Rate Limiter Uses Proxy IP
**File:** `src/api/middleware/rate_limiter.py:43` — Should check `X-Forwarded-For` first.

---

## 🟢 Low Severity

- **L1** — Empty `__init__.py` — no stable public API; callers import internal paths
- **L2** — N+1 lazy load risks in `ticket_repo.py:183-203` and `resolution_repo.py:55-69`
- **L3** — Orchestrator God class (8 responsibilities in one class)
- **L4** — `_build_orchestrator()` 85-line factory function in `dependencies.py`
- **L5** — Health routes return raw dicts (inconsistent with Pydantic response_model pattern)
- **L6** — PII masker silently passes original text on Presidio failure

---

## Non-Issues (Confirmed Good)

- ✅ No circular imports — clean dependency DAG
- ✅ No wildcard imports
- ✅ DB session lifecycle — `get_db()` dependency commits on success, rolls back on error
- ✅ Background task session — fresh session with explicit pre-task commit (no race condition)
- ✅ JWT secret key length validated at startup
- ✅ No hardcoded API keys or AWS credentials
- ✅ pgvector raw SQL justified (operator not in ORM), parameters are bound
- ✅ All main API routes use typed Pydantic response models
- ✅ HTTP status codes are semantically correct
- ✅ `expire_on_commit=False` on session factory (correct for async)
- ✅ `pool_pre_ping=True` (handles stale connections)

---

## Issue Count by Severity

| Severity | Count |
|----------|-------|
| 🔴 Critical | 2 |
| 🟠 High | 3 |
| 🟡 Medium | 7 |
| 🟢 Low | 6 |
| **Total** | **18** |
