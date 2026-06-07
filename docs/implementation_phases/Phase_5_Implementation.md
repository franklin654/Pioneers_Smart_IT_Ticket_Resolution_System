# Phase 5 — Agentic Orchestration

**Project root:** `app_v2/backend/`
**Builds on:** Phases 1–4 complete (ingestion, classification, RAG pipeline all ready).

---

## Context

Phase 5 wires the Phase 3–4 components into an AutoGen multi-agent workflow that drives the full ticket lifecycle. A new ticket enters, agents classify it, retrieve context, generate a resolution, evaluate its quality, then route it deterministically to one of three outcomes: `AUTO_RESOLVED`, `ASSIGNED`, or `ESCALATED`.

The AutoGen agents are built with `pyautogen>=0.2.30` (already in pyproject.toml). Each agent wraps one of our existing service objects and uses AutoGen's `ConversableAgent` base class with custom reply functions — no LLM-for-speaker-selection overhead, and fully async-friendly via `asyncio.to_thread` where the sync AutoGen API must be called.

**Outcome:** `TicketOrchestrator.process_ticket(ticket_id, session)` is the single async entry point for Phase 6 API routes to call.

---

## Files to Create

```
backend/src/routing/
├── router.py            # TicketRouter — decision engine
└── escalation.py        # EscalationDetector — repeated-issue detection

backend/src/agents/
├── classifier_agent.py  # ClassifierAgent(ConversableAgent)
├── rag_agent.py         # RAGAgent(ConversableAgent)
├── evaluator_agent.py   # EvaluatorAgent(ConversableAgent) — LLM-as-judge
├── user_proxy.py        # TicketUserProxy(UserProxyAgent)
└── orchestrator.py      # TicketOrchestrator — sequential flow

backend/tests/unit/
├── test_router.py
├── test_escalation.py
├── test_evaluator_agent.py
└── test_orchestrator.py
```

---

## 1. `src/routing/router.py` — Decision Engine

**Responsibility:** Pure Python decision logic — no LLM, no DB. Takes a `ClassificationOutput` + `llm_quality_score` → returns `(RoutingDecision, assigned_department, escalation_reason)`.

```python
_DEPARTMENT_MAP: dict[TicketCategory, str] = {
    TicketCategory.INFRASTRUCTURE:    "infrastructure-team",
    TicketCategory.APPLICATION:       "application-team",
    TicketCategory.SECURITY:          "security-team",
    TicketCategory.DATABASE:          "database-team",
    TicketCategory.ACCESS_MANAGEMENT: "iam-team",
    TicketCategory.NETWORK:           "network-team",
}

_LLM_QUALITY_THRESHOLD = 3.5   # below this → ESCALATED regardless of confidence


@dataclass(frozen=True)
class RoutingResult:
    decision: RoutingDecision
    assigned_department: str | None   # set for AUTO_RESOLVED and ASSIGNED
    escalation_reason: str | None     # set for ESCALATED


class TicketRouter:
    """Deterministic routing engine: classif output + LLM quality → routing decision.

    Decision rules (checked in order — first match wins):
    1. is_multi_domain=True  → ESCALATED (specialist required)
    2. confidence_level=LOW  → ESCALATED (classifier uncertain)
    3. llm_quality_score < 3.5 → ESCALATED (resolution not actionable)
    4. confidence_level=HIGH → AUTO_RESOLVED (high confidence + good resolution)
    5. confidence_level=MEDIUM → ASSIGNED (agent gets the AI suggestion)
    """

    def decide(
        self,
        classification: ClassificationOutput,
        llm_quality_score: float,
    ) -> RoutingResult: ...
```

**Key details:**
- All 5 rules must be checked in strict order — first match wins
- `assigned_department` uses `_DEPARTMENT_MAP[classification.predicted_category]`
- Escalation reasons are descriptive strings: `"Multi-domain ticket"`, `"Low classifier confidence (0.42)"`, `"Resolution quality below threshold (2.8/5.0)"`
- No external I/O — pure computation, fully unit-testable without any mock

---

## 2. `src/routing/escalation.py` — Repeated-Issue Detection

**Responsibility:** Query the ticket repo for same-category tickets in the past N days. If a pattern is found, flag the resolution as a repeated issue and suggest automation.

```python
@dataclass
class EscalationContext:
    is_repeated_issue: bool
    recurrence_count: int          # how many similar tickets in the window
    automation_suggestion: str | None   # e.g. "Create runbook for DB connection resets"


class EscalationDetector:
    """Detects recurring ticket patterns and suggests automation.

    Args:
        ticket_repo: TicketRepository for DB lookup.
        lookback_days: Window for recurrence detection (default 30).
        recurrence_threshold: Minimum count to flag as repeated (default 3).
    """

    def __init__(
        self,
        ticket_repo: TicketRepository,
        lookback_days: int = 30,
        recurrence_threshold: int = 3,
    ) -> None: ...

    async def check(
        self,
        category: TicketCategory,
        exclude_ticket_id: uuid.UUID,
    ) -> EscalationContext: ...
```

**Implementation details:**
- Query: `SELECT COUNT(*) FROM tickets WHERE category = :cat AND created_at > now() - interval ':days days' AND id != :exclude_id`
- Use `TicketRepository.list()` with filters, or raw SQLAlchemy select
- `automation_suggestion` template: `f"This {category.value} issue has recurred {count} times in the last {days} days — consider creating an automated runbook."`
- If count < threshold: `EscalationContext(is_repeated_issue=False, recurrence_count=count, automation_suggestion=None)`

---

## 3. `src/agents/classifier_agent.py`

**Responsibility:** Wrap `TicketClassifier` inside an AutoGen `ConversableAgent`. Receives a classify request dict, calls `classifier.predict()`, persists the `Classification` row, updates ticket status, returns structured result.

```python
class ClassifierAgent(ConversableAgent):
    """AutoGen agent wrapping the logistic-regression TicketClassifier.

    Uses a custom reply function (not LLM) — llm_config=False.
    Persists Classification ORM row after successful prediction.
    Updates Ticket.status: CLASSIFYING → CLASSIFIED.

    Args:
        classifier: Loaded TicketClassifier instance.
        ticket_repo: TicketRepository for status updates.
        classification_repo: ClassificationRepository for persisting results.
        settings: Application settings.
    """
```

**Message protocol (input dict):**
```python
{
    "type": "CLASSIFY",
    "ticket_id": str(uuid),
    "title": "...",
    "description": "...",   # PII-masked
}
```

**Reply message (output dict):**
```python
{
    "type": "CLASSIFICATION_RESULT",
    "ticket_id": str(uuid),
    "predicted_category": "network",
    "confidence": 0.91,
    "confidence_level": "high",
    "is_multi_domain": False,
    "top_categories": [...],
    "classification_method": "logistic_regression_v...",
}
```

**Implementation:**
- Register reply via `self.register_reply(trigger=ConversableAgent, reply_func=self._do_classify, position=0)`
- `_do_classify` is sync; calls `asyncio.get_event_loop().run_until_complete(self._async_classify(...))`
- On `ClassificationError` → return `{"type": "ERROR", "error_code": "CLASSIFICATION_ERROR", ...}`
- Persist `Classification(ticket_id=..., predicted_category=..., ...)` via `classification_repo.create()`
- Update ticket status: `await ticket_repo.update_status(ticket_id, TicketStatus.CLASSIFIED)`

**Note on Classification repository:** Phase 1 created the `Classification` ORM model and the `BaseRepository`. We need a thin `ClassificationRepository(BaseRepository[Classification])` — it only needs `create()` from base. Create it in `src/db/repositories/classification_repo.py`.

---

## 4. `src/agents/rag_agent.py`

**Responsibility:** Run the full RAG pipeline for a classified ticket: build/load KB index → retrieve → rerank → generate → return resolution text.

```python
class RAGAgent(ConversableAgent):
    """AutoGen agent wrapping the hybrid retriever + MMR reranker + LLM generator.

    Updates Ticket.status: CLASSIFIED → RETRIEVING → GENERATING.

    Args:
        kb: KnowledgeBase (BM25 index already built at startup).
        kb_repo: KnowledgeBaseRepository for dense search.
        reranker: MMRReranker instance.
        rag_generator: RAGGenerator instance.
        embedding_generator: EmbeddingGenerator for query vectors.
        ticket_repo: For status updates.
        settings: Application settings.
    """
```

**Message protocol (input):**
```python
{
    "type": "RETRIEVE_AND_GENERATE",
    "ticket_id": str(uuid),
    "title": "...",
    "description": "...",
    "classification": { ... }   # the CLASSIFICATION_RESULT dict
}
```

**Reply message (output):**
```python
{
    "type": "RESOLUTION_GENERATED",
    "ticket_id": str(uuid),
    "resolution_text": "Step 1: ...",
    "retrieved_entries": [
        {"entry_id": str(uuid), "title": "...", "similarity_score": 0.83},
        ...
    ],
}
```

**Implementation:**
- Parse `category` from `classification["predicted_category"]` → `TicketCategory(value)`
- Build `query_text = f"{title} {description}"`
- `query_vector = embedding_generator.encode_single(query_text)`
- `candidates = await retriever.retrieve(query_text, query_vector, category_filter=category)`
- `reranked = reranker.rerank(candidates, top_k=settings.rag_top_k)`
- `resolution = await rag_generator.generate(title, description, category, reranked)`
- On `RAGRetrievalError` or `LLMUnavailableError` → return `{"type": "ERROR", ...}`

---

## 5. `src/agents/evaluator_agent.py` — LLM-as-Judge

**Responsibility:** Call the LLM to score the generated resolution on 3 dimensions (Relevance, Completeness, Actionability). Returns a score 0–5.0.

```python
class EvaluatorAgent(ConversableAgent):
    """AutoGen agent that uses an LLM to evaluate resolution quality.

    Sends a structured evaluation prompt and parses a JSON response.
    Falls back to score=0.0 if the LLM response cannot be parsed.

    Args:
        llm_generator: LLMGeneratorProtocol instance (Ollama or Claude).
        ticket_repo: For status updates.
        settings: Application settings.
    """
```

**Evaluation prompt:**
```
You are an IT resolution quality evaluator.
Rate this resolution on 3 dimensions, each 0–5:
- relevance: Does it address the specific issue described?
- completeness: Are all necessary steps included?
- actionability: Are steps clear and immediately executable?

Ticket: {title}
Description: {description}
Resolution: {resolution_text}

Respond ONLY with valid JSON, no other text:
{"relevance": <0-5>, "completeness": <0-5>, "actionability": <0-5>}
```

**JSON parsing:**
- Use `json.loads()` on the raw LLM response
- Clamp each dimension to [0.0, 5.0]
- `quality_score = (relevance + completeness + actionability) / 3`
- On parse failure → `quality_score = 0.0`, log a warning
- Update ticket status: GENERATING → EVALUATING

**Reply message (output):**
```python
{
    "type": "EVALUATION_RESULT",
    "ticket_id": str(uuid),
    "quality_score": 4.1,
    "dimension_scores": {"relevance": 4.5, "completeness": 4.0, "actionability": 3.8},
}
```

---

## 6. `src/agents/user_proxy.py`

**Responsibility:** Represents the system/human interface in the AutoGen conversation. Initiates the conversation, collects the final evaluation result, and triggers routing. Does NOT represent a human user — `human_input_mode="NEVER"`.

```python
class TicketUserProxy(UserProxyAgent):
    """AutoGen UserProxyAgent that drives the agent pipeline and enforces routing.

    - Initiates the agent conversation with the CLASSIFY message
    - Receives EVALUATION_RESULT as the terminal message
    - Calls TicketRouter to get the routing decision
    - Persists Resolution and updates Ticket.status to final state

    Args:
        router: TicketRouter for the final routing decision.
        resolution_repo: ResolutionRepository for persisting results.
        ticket_repo: For final status update.
        settings: Application settings.
    """
```

**Key configuration:**
- `human_input_mode="NEVER"` — fully automated
- `is_termination_msg=lambda msg: msg.get("type") == "EVALUATION_RESULT"` — stop when evaluator responds
- On termination: call `router.decide(classification, quality_score)` → persist `Resolution` row → update `Ticket.status`

---

## 7. `src/agents/orchestrator.py` — Sequential Orchestrator

**Responsibility:** Creates and coordinates all agents in a sequential two-agent chat pattern (not GroupChat). Provides the single async entry point `process_ticket()`.

```python
class TicketOrchestrator:
    """Coordinates the full ticket processing pipeline via AutoGen agents.

    Sequential flow:
        proxy → ClassifierAgent → proxy → RAGAgent → proxy → EvaluatorAgent → routing

    Each two-agent exchange uses max_turns=1; the orchestrator threads the
    result from each stage into the next message.

    Args:
        classifier_agent: ClassifierAgent instance.
        rag_agent: RAGAgent instance.
        evaluator_agent: EvaluatorAgent instance.
        proxy: TicketUserProxy instance.
        escalation_detector: EscalationDetector for repeated-issue check.
        ticket_repo: For loading and updating the ticket.
    """

    async def process_ticket(
        self,
        ticket_id: uuid.UUID,
        session: AsyncSession,
    ) -> Resolution:
        """Run the full pipeline for a ticket and return the persisted Resolution.

        Steps:
        1. Load ticket from DB (must be in NEW status)
        2. Update status → CLASSIFYING; call ClassifierAgent
        3. Update status → CLASSIFIED; call RAGAgent
        4. Update status → EVALUATING; call EvaluatorAgent
        5. Run EscalationDetector
        6. Call TicketRouter to get routing decision
        7. Persist Resolution; update Ticket.status to final
        8. Return Resolution

        Raises:
            TicketNotFoundError: If ticket_id does not exist.
            ClassificationError: If classification fails and cannot be recovered.
        """
        ...
```

**How agents are called (sync wrapped in asyncio.to_thread):**
```python
# ClassifierAgent call
classify_msg = {"type": "CLASSIFY", "ticket_id": str(ticket_id), ...}
await asyncio.to_thread(
    proxy.initiate_chat,
    classifier_agent,
    message=json.dumps(classify_msg),
    max_turns=1,
    silent=True,
)
classification_msg = proxy.last_message(classifier_agent)
```

**Error recovery:**
- If ClassifierAgent returns `{"type": "ERROR"}` → immediately escalate: create a `Resolution(routing_decision=ESCALATED, escalation_reason="Classification failed")`, update status, return
- If RAGAgent returns `{"type": "ERROR"}` → same escalation path
- EvaluatorAgent never hard-fails (falls back to quality_score=0.0)

**Factory method:**
```python
@classmethod
def from_settings(
    cls,
    settings: Settings,
    session: AsyncSession,
) -> "TicketOrchestrator":
    """Build the full agent graph from settings and a DB session."""
    ...
```

---

## 8. New Repository: `src/db/repositories/classification_repo.py`

A thin wrapper around `BaseRepository[Classification]`. Only needs what `BaseRepository` provides (`create`, `get_by_id`). Add a `get_by_ticket_id(ticket_id: UUID) -> Classification | None` query.

```python
class ClassificationRepository(BaseRepository[Classification]):
    model_class = Classification

    async def get_by_ticket_id(self, ticket_id: uuid.UUID) -> Classification | None:
        result = await self._session.execute(
            select(Classification).where(Classification.ticket_id == ticket_id)
        )
        return result.scalar_one_or_none()
```

---

## 9. Unit Tests

### `tests/unit/test_router.py`

Pure Python — no DB, no LLM. Tests all 5 routing rules.

**Happy path:**
- HIGH confidence + not multi-domain + score ≥3.5 → AUTO_RESOLVED
- MEDIUM confidence + not multi-domain + score ≥3.5 → ASSIGNED
- Each TicketCategory maps to its expected department string

**Escalation triggers:**
- `is_multi_domain=True` → ESCALATED (regardless of confidence or score)
- `confidence_level=LOW` + score ≥3.5 → ESCALATED
- HIGH confidence + score <3.5 → ESCALATED
- MEDIUM confidence + score <3.5 → ESCALATED
- is_multi_domain=True overrides HIGH confidence + high score

**Edge cases:**
- Score exactly 3.5 → NOT escalated (threshold is strictly less than 3.5)
- Score 0.0 (evaluator parse failure) → ESCALATED
- All 6 categories produce non-None `assigned_department` for AUTO_RESOLVED

### `tests/unit/test_escalation.py`

Mocked TicketRepository.

- `recurrence_count < threshold` → `is_repeated_issue=False`, no suggestion
- `recurrence_count >= threshold` → `is_repeated_issue=True`, suggestion string contains category name
- Exclude ticket ID not included in count
- Uses lookback_days from config

### `tests/unit/test_evaluator_agent.py`

Mocked LLM generator.

- Valid JSON response → scores parsed correctly, `quality_score = mean of 3`
- Valid JSON with float values → clamped to [0, 5]
- LLM returns extra text before/after JSON → still parses correctly (try `re.search(r'\{.*?\}', response, re.DOTALL)`)
- Invalid JSON response → `quality_score = 0.0`, no exception raised
- Empty LLM response → `quality_score = 0.0`
- Scores outside [0,5] in JSON → clamped

### `tests/unit/test_orchestrator.py`

All agents mocked — tests flow logic, status transitions, and error recovery.

- Normal flow: classify → RAG → evaluate → route → Resolution persisted
- ClassifierAgent returns ERROR → Resolution with ESCALATED created, no RAG/evaluator call
- RAGAgent returns ERROR → Resolution with ESCALATED, no evaluator call
- Correct ticket status transitions at each step
- Repeated-issue flag set on Resolution when EscalationDetector returns `is_repeated_issue=True`

---

## Existing code to reuse

| What | Location |
|---|---|
| `ClassificationOutput`, `ConfidenceLevel` | `src/classification/confidence.py` |
| `TicketClassifier.predict()` | `src/classification/classifier.py` |
| `HybridRetriever.retrieve()` | `src/rag/retriever.py` |
| `MMRReranker.rerank()` | `src/rag/reranker.py` |
| `RAGGenerator.generate()`, `LLMGeneratorFactory` | `src/rag/generator.py` |
| `EmbeddingGenerator.encode_single()` | `src/embedding/generator.py` |
| `KnowledgeBase` | `src/rag/knowledge_base.py` |
| `TicketRepository.update_status()`, `get_by_id()` | `src/db/repositories/ticket_repo.py` |
| `ResolutionRepository.create()` | `src/db/repositories/resolution_repo.py` |
| `KnowledgeBaseRepository` | `src/db/repositories/knowledge_base_repo.py` |
| `TicketNotFoundError`, `LLMUnavailableError`, `ClassificationError` | `src/core/exceptions.py` |
| `RoutingDecision`, `TicketStatus`, `TicketCategory`, `ConfidenceLevel` | `src/db/models.py` |
| `Resolution`, `Classification`, `FeedbackLog` ORM models | `src/db/models.py` |
| `get_settings()` | `src/core/config.py` |
| `get_logger()` | `src/core/logging.py` |

**ag2 classes (drop-in for pyautogen 0.2.x — `import autogen` unchanged):**
- `autogen.ConversableAgent` — base for ClassifierAgent, RAGAgent, EvaluatorAgent
- `autogen.UserProxyAgent` — base for TicketUserProxy
- `proxy.initiate_chat(agent, message=..., max_turns=1, silent=True)` — two-agent exchange
- `proxy.last_message(agent)` — retrieve the agent's last reply

Replace `"pyautogen>=0.2.30"` with `"ag2>=0.3.0"` in `pyproject.toml`.

---

## Verification

```bash
# 1. Unit tests for routing and escalation (pure Python, fast)
mamba run -n ticket_routing python -m pytest tests/unit/test_router.py tests/unit/test_escalation.py -v

# 2. Unit tests for evaluator and orchestrator (mocked agents)
mamba run -n ticket_routing python -m pytest tests/unit/test_evaluator_agent.py tests/unit/test_orchestrator.py -v

# 3. Full unit suite (should stay ≥70% coverage)
mamba run -n ticket_routing python -m pytest tests/unit/ -v
```
