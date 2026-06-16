# Lessons Learned — v1 → v2

v1 was built from [`00_PROBLEM_STATEMENT.md`](00_PROBLEM_STATEMENT.md) and an initial
implementation plan that, in places, didn't survive contact with the real
engineering tradeoffs. This document is the honest record of what changed, why, and
what we're carrying forward unchanged into v2. Every decision in
[`02_ARCHITECTURE.md`](02_ARCHITECTURE.md) onward traces back to a row in this table.

## Architectural deviations — kept, because they were the right call

| Original plan | What v1 actually did | v2 decision |
|---|---|---|
| Angular 17 + Angular Material frontend | React 19 + Vite 6 + TypeScript, custom hooks, Tailwind | **Keep React.** No functional reason favored Angular; React's hooks model fit the polling/WebSocket-driven UI better and the team shipped faster in it. |
| AutoGen `GroupChat` with 4 agents (`Coordinator`, `Classifier`, `RAG`, `Escalation`) negotiating ticket fate over a shared conversation | Deterministic `TicketOrchestrator` driving sequential single-shot `initiate_chat` calls; `Coordinator`/`Escalation` were never built as agents — their logic became plain Python (`TicketRouter`, `EscalationDetector`) | **Keep the deterministic pipeline, but stop pretending otherwise.** `GroupChat` is for open-ended "who speaks next" conversations; this problem has exactly one valid execution order, hard numeric thresholds (0.60/0.85 confidence, 3.5 quality) that must be auditable and unit-testable, and a p95 < 5s latency budget that can't absorb extra LLM round-trips for an LLM-mediated "Coordinator" to decide routing. v2 documents this as the *intended* design from day one — see [`03_BACKEND_DESIGN.md` § Pipeline Stages](03_BACKEND_DESIGN.md). |
| MD5 exact-match dedup + 0.95 fixed near-duplicate threshold | SHA-256 (avoids security-linter findings) + a named, configurable `dedup_similarity_threshold` setting | **Keep SHA-256 + configurable threshold.** Strictly better; no reason to regress. |
| Kaggle CSV dataset as the training/eval corpus | Fully synthetic, Claude-generated train/test ticket corpus; Kaggle/UCI/ServiceNow loaders deleted | **Keep synthetic generation as the canonical source.** Reproducible, license-clean, and lets us control category balance and difficulty (including deliberately ambiguous tickets to exercise the confidence/escalation path). |
| 4 evaluators (classification, RAG, LLM-judge, end-to-end) | 6 evaluators shipped: the original 4 plus `routing_accuracy_eval` and `holdout_eval` | **Keep all 6, formalize them as the baseline suite**, not an undocumented add-on. |

## The one real gap — fixed at the design level, not patched on top

**Original plan's own architecture diagram** showed confidence branching *before*
RAG ran (`HIGH → RAG`, `LOW/MULTI-DOMAIN → ESCALATE` straight off the confidence
scorer). **v1's actual code never built that gate** — the orchestrator ran
classify → RAG → generate → evaluate → route unconditionally for every ticket, and
only decided ASSIGNED vs. ESCALATED at the very end. A ticket the classifier was
uncertain about still got a full LLM-generated resolution before being escalated,
and there was no way for a human to correct a wrong/ambiguous category and have the
pipeline resume — escalation was a dead end.

**v2 builds the gate from the start:** classification confidence and multi-domain
detection are checked immediately after Stage 1. If either trips, the pipeline halts
*before* RAG/generation, the ticket moves to a new `AWAITING_REVIEW` status (distinct
from terminal `ESCALATED`), and a human can submit a corrected category via a new
`PATCH /tickets/{id}/reclassify` endpoint, which resumes the pipeline from the RAG
stage with that category trusted as high-confidence. Full design in
[`03_BACKEND_DESIGN.md` § Pre-Generation Gate](03_BACKEND_DESIGN.md) and
[`04_FRONTEND_DESIGN.md` § Reclassification Flow](04_FRONTEND_DESIGN.md).

## UAT findings folded into the redesign

| ID | Finding | v2 disposition |
|---|---|---|
| KB-05 | Resolution steps stored as raw LLM markdown text; frontend had to regex-split it into a list, which mis-grouped sub-bullets | **Backend generates and stores structured steps** (`list[{step_number, instruction}]`) instead of free text. No client-side markdown parsing needed — see [`03_BACKEND_DESIGN.md` § Resolution Schema](03_BACKEND_DESIGN.md). |
| INT-10 | Auto-classified category wasn't written back to `tickets.category`, so list/filter views showed nothing | **Fixed in v1 already; formalized as the default behavior** — classification always backfills `tickets.category` when the ticket was submitted without one. |
| INT-11 | LinearSVC classifier struggles on ambiguous/technical phrasing | **Not solved by a bigger model in v2 MVP** (out of scope/cost). Instead, the pre-generation gate means low-confidence tickets now get a *correct* outcome (human reclassification) instead of a wrong one (bad auto-resolution). A model upgrade or LLM-assisted second-opinion classification is recorded as a deferred enhancement, not blocking. |
| AGT-01 | No way to deselect a ticket in the sandbox view | Confirmed intentional (most-recent-ticket default); no change. |
| INT-04 | Submit button spinner imperceptible on fast localhost requests | Not a bug; UI code is correct, behavior is just too fast to notice locally. No change. |

## Code-audit issues (18 found in v1) — baked into v2 from the start

Rather than retrofit fixes, every issue from the v1 code audit is addressed in the
relevant v2 module design (see [`03_BACKEND_DESIGN.md` § Audit Fixes](03_BACKEND_DESIGN.md)
for the full mapping):

- **Critical:** dead `asyncio.run()` calls in AutoGen reply handlers (never built,
  since v2 doesn't route through AutoGen's message-passing protocol at all);
  `await session.delete()` misuse in the base repository.
- **High:** CPU-bound ML inference (classifier predict, embedding encode, MMR
  rerank) wrapped in `asyncio.to_thread()` from the first commit, not added later;
  no hardcoded default admin password — config fails closed if unset; trainer uses
  the repository layer exclusively, never reaches into `.session` directly.
- **Medium/Low:** specific exception types instead of broad `except Exception`;
  blocking file I/O (pickle load/dump for BM25 index) wrapped in `asyncio.to_thread`;
  no raw SQL f-strings; bounded KB loads; indexes on every filtered/sorted column from
  the first migration; CORS methods/headers explicitly enumerated, never `"*"`;
  rate limiter checks `X-Forwarded-For` first; non-empty `__init__.py` public APIs;
  Pydantic response models on every route including health.

## Auth gap

v1's config had `refresh_token_expire_days` defined but **no `/auth/refresh`
endpoint was ever implemented** — access tokens just expired with no renewal path.
v2 implements the refresh flow properly (short-lived access token + `HttpOnly`
refresh cookie), per [`CLAUDE.md`](../CLAUDE.md) backend auth guidance. See
[`05_API_CONTRACT.md`](05_API_CONTRACT.md).

## Response envelope

v1's API returned raw Pydantic models with no consistent success/error envelope.
[`CLAUDE.md`](../CLAUDE.md) §4.3 specifies a `{ "data": ..., "meta": ... }` /
`{ "error": {...} }` envelope — v2 adopts it from the first endpoint, documented in
[`05_API_CONTRACT.md`](05_API_CONTRACT.md).
