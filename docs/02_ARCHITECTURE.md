# System Architecture (v2)

## Pipeline

```
Ticket In
    │
    ▼
[Ingestion Pipeline]  ← validate, PII mask (Presidio), dedupe (SHA-256 exact + embedding near-dup)
    │
    ▼
[Embedding Generator]  ← sentence-transformers/all-MiniLM-L6-v2 (384-dim)
    │
    ▼
[Classifier]  ← LinearSVC + CalibratedClassifierCV
    │
    ▼
[Confidence Scorer]  ← HIGH / MEDIUM / LOW + multi-domain detection
    │
    ├─── LOW confidence  ──┐
    ├─── multi-domain ─────┤
    │                      ▼
    │              [AWAITING_REVIEW]  ← pipeline halts here, no RAG/generation yet
    │                      │
    │              Human picks correct category
    │              PATCH /tickets/{id}/reclassify
    │                      │
    │                      ▼
    │              (re-enters below as HIGH confidence, classification_method="human_reviewer")
    │
    ▼ HIGH / MEDIUM confidence, not multi-domain
[RAG]
    ├── Dense retrieval (pgvector, 70% weight)
    ├── BM25 keyword retrieval (30% weight)
    └── MMR reranking (λ = 0.7)
    │
    ▼
[LLM Generator]  ← Ollama (Mistral-7B) or Claude API, structured step output
    │
    ▼
[Evaluator]  ← LLM-as-judge: Relevance + Completeness + Actionability
    │
    ▼
[Router]  ← deterministic decision engine
    │
    ├── score ≥ 3.5, confidence HIGH       → AUTO_RESOLVED
    ├── score ≥ 3.5, confidence MEDIUM     → ASSIGNED (+ AI suggestion)
    └── score < 3.5                        → ESCALATED (quality gate failed post-generation)
```

This is the gate v1's own original diagram intended but never built into the code —
see [`01_LESSONS_LEARNED.md`](01_LESSONS_LEARNED.md). The pipeline now has two
distinct "needs a human" outcomes, not one:

| Status | When | Pipeline state | Resolvable by |
|---|---|---|---|
| `AWAITING_REVIEW` | Low confidence or multi-domain, **pre-generation** | Halted before RAG/generation — nothing wasted | Human picks category → pipeline resumes |
| `ESCALATED` | Quality score < 3.5, **post-generation** | Full pipeline ran, resolution exists but isn't good enough | Human reviews the generated (low-quality) resolution directly — nothing to reclassify |

## Pipeline Stages as Components, Not a Negotiation

Each pipeline stage is implemented as a single-purpose `autogen.ConversableAgent`
subclass (`ClassifierAgent`, `RAGAgent`, `EvaluatorAgent`) — kept for a consistent
"replaceable, message-shaped" interface and because AutoGen's tool-calling primitives
remain useful for the LLM generation/evaluation stages specifically. They are
**called directly as coroutines by a deterministic orchestrator**, not connected via
`GroupChat` or `initiate_chat`. Routing and escalation decisions are explicitly
**not** agents — `TicketRouter` and `EscalationDetector` are plain, fully
unit-testable Python classes with no LLM in the loop, because their thresholds must
be exact and reproducible. Full design in
[`03_BACKEND_DESIGN.md`](03_BACKEND_DESIGN.md).

## Technology Stack

| Layer | Technology | Change from v1 plan |
|---|---|---|
| API | FastAPI (async) | — |
| ORM | SQLAlchemy 2.0 (async) | — |
| Database | PostgreSQL 16 + pgvector | — |
| Embedding | sentence-transformers/all-MiniLM-L6-v2 (384-dim) | — |
| Classifier | scikit-learn LinearSVC + CalibratedClassifierCV | — |
| BM25 | rank-bm25 | — |
| LLM | Ollama (Mistral-7B) / Claude API — env-controlled | — |
| Pipeline stages | AutoGen `ConversableAgent` per stage, called directly (no `GroupChat`) | **Changed** — documents v1's actual (and correct) implementation |
| Routing / escalation | Plain deterministic Python (`TicketRouter`, `EscalationDetector`) | **Changed** — never agents; v1 plan implied otherwise |
| PII Detection | Microsoft Presidio | — |
| Auth | PyJWT + bcrypt, access + refresh tokens | **Changed** — refresh flow actually implemented |
| Frontend | React 19 + Vite 6 + TypeScript + Tailwind | **Changed** from Angular 17 |
| Monitoring | Prometheus + Grafana | — |
| Deployment | Docker Compose | — |
| Testing | pytest + pytest-asyncio (backend), Vitest + Testing Library (frontend) | — |

## Project Structure

```
backend/
├── src/
│   ├── core/            # config, logging, exceptions
│   ├── db/               # models, session, repositories
│   ├── schemas/          # Pydantic v2 request/response schemas
│   ├── ingestion/        # validator, pii_masker, deduplicator, pipeline
│   ├── embedding/        # generator, pgvector store
│   ├── classification/   # classifier, trainer, confidence scorer
│   ├── rag/               # retriever, reranker, generator, knowledge_base
│   ├── agents/            # ClassifierAgent, RAGAgent, EvaluatorAgent, orchestrator
│   ├── routing/           # TicketRouter, EscalationDetector (plain Python)
│   ├── api/                # routes, middleware, websocket
│   └── monitoring/         # Prometheus metrics, health checks
├── scripts/                # setup_db, generate_synthetic_data, load_tickets, train_classifier
├── data/                   # raw/ (synthetic CSVs), processed/, models/
├── tests/                  # unit/, integration/
├── evaluation/              # classification_eval, rag_eval, llm_judge, end_to_end_eval,
│                              routing_accuracy_eval, holdout_eval
└── pyproject.toml

frontend/
├── src/
│   ├── types.ts
│   ├── api/                # typed client
│   ├── hooks/               # useAuth, useTickets, useWebSocket
│   ├── features/            # intake/, resolution/, kb/, agent-sandbox/, analytics/, auth/
│   └── shared/                # cross-feature components, constants, utils
└── package.json

docker/
├── docker-compose.yml
├── docker-compose.dev.yml
├── prometheus.yml
└── grafana/
```

See [`03_BACKEND_DESIGN.md`](03_BACKEND_DESIGN.md) and
[`04_FRONTEND_DESIGN.md`](04_FRONTEND_DESIGN.md) for the detailed module-by-module
design.
