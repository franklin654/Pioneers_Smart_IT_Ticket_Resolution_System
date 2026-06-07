# Phase 2 — Implementation Plan: Ingestion Pipeline

**Project root:** `app_v2/backend/`  
**Builds on:** Phase 1 (models, repositories, schemas, config, exceptions all in place)

---

## Context

Phase 2 implements the ingestion pipeline — the first stage every incoming ticket passes through before any ML processing. A ticket submitted to `POST /api/v1/tickets/ingest` must be:

1. **Validated** — schema conformance, field constraints, HTML sanitization
2. **PII-masked** — sensitive entities detected and replaced before persistence
3. **Deduplicated** — exact (hash) and near (embedding similarity) duplicate detection
4. **Persisted** — saved to the `tickets` table
5. **Handed off** — ingestion result returned; async embedding + classification triggered in later phases

The pipeline is a strict 5-stage sequential flow with a clear contract between stages. Each stage is an independently testable class with a single responsibility. The orchestrating `IngestionPipeline` class composes them and provides the single entry point for the API layer (Phase 6).

**Latency target:** < 205 ms end-to-end (synchronous path only; embedding is async)

---

## Files to Create

```
backend/src/ingestion/
├── __init__.py                 # already exists (empty)
├── validator.py                # Stage 1 — schema validation + sanitization
├── pii_masker.py               # Stage 2 — Presidio PII detection + masking
├── deduplicator.py             # Stage 3 — MD5 exact + embedding near-duplicate
└── pipeline.py                 # Orchestrator — composes all stages

backend/tests/unit/
├── test_validator.py
├── test_pii_masker.py
└── test_deduplicator.py

backend/tests/integration/
└── test_ingestion_pipeline.py
```

---

## Stage Contracts

Each stage receives an `IngestionContext` dataclass that accumulates state as it flows through the pipeline. No stage mutates the original request — each returns an updated context.

```python
@dataclass
class IngestionContext:
    # Set at entry
    raw_title: str
    raw_description: str
    priority: int
    category_hint: TicketCategory | None
    source: TicketSource

    # Populated by validator (Stage 1)
    clean_title: str | None = None
    clean_description: str | None = None

    # Populated by PII masker (Stage 2)
    masked_description: str | None = None
    pii_detected: bool = False
    pii_entity_types: list[str] = field(default_factory=list)

    # Populated by deduplicator (Stage 3)
    content_hash: str | None = None
    duplicate_type: str | None = None        # "exact" | "near" | None
    existing_ticket_id: str | None = None

    # Populated by persister (Stage 4)
    ticket_id: uuid.UUID | None = None
    ticket_status: TicketStatus | None = None
```

---

## File-by-File Specification

---

### `backend/src/ingestion/validator.py`

**Responsibility:** Validate field constraints and sanitize raw text input.

```python
class TicketValidator:
    """Validates and sanitizes raw ticket input.

    Sanitization rules applied in order:
        1. Strip leading/trailing whitespace
        2. Collapse internal whitespace runs to single spaces
        3. Strip HTML tags (prevent XSS in downstream rendering)
        4. Enforce minimum/maximum length after sanitization
        5. Validate priority is in range [1, 5]
        6. Validate category hint is a known TicketCategory (if provided)

    Raises:
        ValidationError: If any field fails its constraint after sanitization.
    """

    # Length constraints (post-sanitization)
    TITLE_MIN = 3
    TITLE_MAX = 200
    DESC_MIN = 10
    DESC_MAX = 5000

    def validate(self, ctx: IngestionContext) -> IngestionContext:
        """Run all validation and sanitization steps.

        Args:
            ctx: Ingestion context with raw_title and raw_description populated.

        Returns:
            Updated context with clean_title and clean_description populated.

        Raises:
            ValidationError: On any constraint violation.
        """
        ...

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """Strip HTML tags, normalize whitespace."""
        ...

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML/XML tags using a simple regex (no external dep needed)."""
        ...
```

**Key implementation details:**

- HTML stripping via `re.sub(r'<[^>]+>', '', text)` — no BeautifulSoup dependency
- Whitespace normalization: `" ".join(text.split())`
- After sanitization, re-check min/max lengths and raise `ValidationError` with field name in `detail`
- Priority validation: must be int in [1, 5]
- Populate `ctx.clean_title` and `ctx.clean_description`

---

### `backend/src/ingestion/pii_masker.py`

**Responsibility:** Detect and mask 8 PII entity types using Microsoft Presidio.

```python
class PIIMasker:
    """Detects and masks personally identifiable information using Presidio.

    Supported entity types (8):
        PERSON, EMAIL_ADDRESS, PHONE_NUMBER, US_SSN,
        CREDIT_CARD, IP_ADDRESS, DATE_TIME, LOCATION

    Masking strategy: Replace each detected entity with its type tag,
    e.g. <EMAIL_ADDRESS>, <PHONE_NUMBER>. This preserves text structure
    and length approximation while removing sensitive data.

    The original description is preserved in ``original_description`` on
    the Ticket model for audit purposes. Only the masked text is used for
    ML operations.
    """

    SUPPORTED_ENTITIES = [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SSN",
        "CREDIT_CARD",
        "IP_ADDRESS",
        "DATE_TIME",
        "LOCATION",
    ]

    def __init__(self) -> None:
        # Lazy-loaded on first call — Presidio model loading is slow
        self._analyzer: AnalyzerEngine | None = None
        self._anonymizer: AnonymizerEngine | None = None

    def mask(self, ctx: IngestionContext) -> IngestionContext:
        """Run PII detection and masking on the clean description.

        Args:
            ctx: Context with clean_description populated.

        Returns:
            Updated context with masked_description, pii_detected,
            and pii_entity_types populated.
        """
        ...

    def _get_analyzer(self) -> AnalyzerEngine:
        """Lazy-initialize Presidio AnalyzerEngine (loads spaCy model once)."""
        ...

    def _get_anonymizer(self) -> AnonymizerEngine:
        """Lazy-initialize Presidio AnonymizerEngine."""
        ...

    def _build_anonymizer_config(self) -> dict[str, OperatorConfig]:
        """Build per-entity operator config that replaces with <ENTITY_TYPE> tags."""
        ...
```

**Key implementation details:**

- Lazy init: `AnalyzerEngine` and `AnonymizerEngine` are created on first call, then cached on `self`. This avoids slow startup; the engine loads when the first ticket is ingested.
- `AnalyzerEngine` configured with `language="en"`, `entities=SUPPORTED_ENTITIES`
- `AnonymizerEngine` uses `OperatorConfig("replace", {"new_value": "<{entity_type}>"})` for all entity types
- Title is NOT masked (too short for reliable PII extraction; also serves as a display key)
- Populate `ctx.masked_description`, `ctx.pii_detected` (bool), `ctx.pii_entity_types` (list of detected type strings)
- On any Presidio error: log warning, fall back to returning original text with `pii_detected=False` — never block ingestion due to PII masker failure

---

### `backend/src/ingestion/deduplicator.py`

**Responsibility:** Detect exact and near-duplicate tickets before persistence.

```python
class DuplicateCheckResult:
    """Result of the deduplication check."""
    is_duplicate: bool
    duplicate_type: str | None   # "exact" | "near" | None
    existing_ticket_id: str | None
    content_hash: str


class Deduplicator:
    """Detects exact and near-duplicate incoming tickets.

    Two-pass strategy:
        Pass 1 — Exact match: SHA-256 hash of normalized (title + description)
            checked against the tickets.content_hash unique index.
            Cost: one indexed DB read.

        Pass 2 — Near-duplicate: If no exact match, check pgvector
            embedding similarity against embeddings created within the last
            ``dedup_window_days`` days. If cosine similarity >= threshold,
            treat as near-duplicate.
            Cost: one ANN vector query (fast via IVFFlat index).

    Note: Pass 2 requires an embedding for the incoming ticket. The
    embedding is generated inline during deduplication (not stored yet).
    If the embedding service is unavailable, Pass 2 is skipped and only
    exact matching is performed — never blocks ingestion.
    """

    def __init__(
        self,
        ticket_repo: TicketRepository,
        embedding_repo: EmbeddingRepository,
        embedding_generator,   # EmbeddingGenerator injected; avoids circular import
        settings: Settings,
    ) -> None:
        ...

    async def check(self, ctx: IngestionContext) -> DuplicateCheckResult:
        """Run both deduplication passes.

        Args:
            ctx: Context with clean_title and clean_description populated.

        Returns:
            DuplicateCheckResult with is_duplicate, duplicate_type,
            existing_ticket_id, and content_hash.
        """
        ...

    async def _check_exact(self, content_hash: str) -> str | None:
        """Return existing ticket ID if exact hash match found, else None."""
        ...

    async def _check_near(self, text: str) -> str | None:
        """Generate embedding and search for similar tickets within window.

        Returns existing ticket ID if similarity >= threshold, else None.
        Silently skips on embedding failure.
        """
        ...
```

**Key implementation details:**

- `content_hash` = `TicketRepository.compute_content_hash(clean_title, clean_description)`
- Exact check: `ticket_repo.get_by_hash(content_hash)` — returns existing ticket ID or None
- Near check: generate embedding for `clean_title + " " + clean_description`, call `embedding_repo.find_similar(vector, top_k=1, similarity_threshold=settings.dedup_similarity_threshold)`
- If `find_similar` returns a result with score ≥ threshold → near duplicate
- Near check silently skips (logs warning) if embedding generation raises `EmbeddingError` — ingestion must not fail due to embedding unavailability
- Populates `ctx.content_hash`, `ctx.duplicate_type`, `ctx.existing_ticket_id`

---

### `backend/src/ingestion/pipeline.py`

**Responsibility:** Orchestrate all ingestion stages and produce the final ingestion result.

```python
@dataclass
class IngestionResult:
    """Final result returned by the ingestion pipeline."""
    ticket_id: uuid.UUID
    status: TicketStatus
    is_duplicate: bool
    duplicate_type: str | None
    existing_ticket_id: str | None
    pii_detected: bool
    message: str


class IngestionPipeline:
    """Orchestrates the 5-stage ticket ingestion flow.

    Stages:
        1. Validate   — TicketValidator.validate(ctx)
        2. Mask PII   — PIIMasker.mask(ctx)
        3. Deduplicate — Deduplicator.check(ctx)
        4. Persist    — Save Ticket to DB
        5. Return     — Build IngestionResult

    A DuplicateTicketError is raised at Stage 3 if a duplicate is detected.
    All other stages raise ValidationError or AppBaseException subclasses
    on failure.

    The pipeline does NOT trigger embedding generation or classification —
    those are async background tasks triggered by the API layer (Phase 6).
    """

    def __init__(
        self,
        validator: TicketValidator,
        pii_masker: PIIMasker,
        deduplicator: Deduplicator,
        ticket_repo: TicketRepository,
        settings: Settings,
    ) -> None:
        ...

    async def run(self, request: TicketIngestRequest) -> IngestionResult:
        """Execute all ingestion stages for an incoming ticket.

        Args:
            request: Validated Pydantic request schema from the API layer.

        Returns:
            IngestionResult with ticket_id, status, and processing metadata.

        Raises:
            ValidationError: If sanitized fields fail constraints.
            DuplicateTicketError: If the ticket is an exact or near-duplicate.
            AppBaseException subclasses: On unexpected stage failures.
        """
        ...

    async def _persist(self, ctx: IngestionContext) -> Ticket:
        """Create and save the Ticket ORM object from the final context state."""
        ...
```

**Key implementation details:**

- Build `IngestionContext` from `TicketIngestRequest` at entry
- Stage 1 (Validate): call `validator.validate(ctx)` — raises `ValidationError` on failure
- Stage 2 (Mask PII): call `pii_masker.mask(ctx)` — never raises (falls back on failure)
- Stage 3 (Deduplicate): call `deduplicator.check(ctx)` — if `is_duplicate=True`, raise `DuplicateTicketError(existing_ticket_id, duplicate_type)`
- Stage 4 (Persist): create `Ticket` ORM instance using `masked_description` for `description`, raw input for `original_description`, `content_hash` from deduplicator; call `ticket_repo.create(ticket)`
- Stage 5 (Return): return `IngestionResult` with `ticket_id`, `status=TicketStatus.NEW`, duplication and PII metadata

**Dependency injection:** All dependencies injected via `__init__` — no singletons inside the pipeline. The API layer (Phase 6) will construct the pipeline using FastAPI's `Depends()` mechanism.

**Factory function** in `pipeline.py`:

```python
def build_ingestion_pipeline(session: AsyncSession) -> IngestionPipeline:
    """Construct a fully-wired IngestionPipeline for use in FastAPI endpoints."""
    settings = get_settings()
    ticket_repo = TicketRepository(session)
    embedding_repo = EmbeddingRepository(session)
    # EmbeddingGenerator imported here to avoid circular imports
    from src.embedding.generator import EmbeddingGenerator
    embedding_gen = EmbeddingGenerator(settings)
    deduplicator = Deduplicator(ticket_repo, embedding_repo, embedding_gen, settings)
    return IngestionPipeline(
        validator=TicketValidator(),
        pii_masker=PIIMasker(),
        deduplicator=deduplicator,
        ticket_repo=ticket_repo,
        settings=settings,
    )
```

Note: `EmbeddingGenerator` is a Phase 3 deliverable. For Phase 2, the `Deduplicator` will accept an optional embedding generator and skip the near-duplicate check if it is `None` or raises an error. This keeps Phase 2 independently runnable and testable without Phase 3.

---

### `IngestionContext` dataclass — defined in `pipeline.py`

```python
from dataclasses import dataclass, field
import uuid
from src.db.models import TicketCategory, TicketSource, TicketStatus

@dataclass
class IngestionContext:
    # ── Input (set at entry) ─────────────────────
    raw_title: str
    raw_description: str
    priority: int
    category_hint: TicketCategory | None
    source: TicketSource

    # ── Stage 1: Validator ───────────────────────
    clean_title: str | None = None
    clean_description: str | None = None

    # ── Stage 2: PII Masker ──────────────────────
    masked_description: str | None = None
    pii_detected: bool = False
    pii_entity_types: list[str] = field(default_factory=list)

    # ── Stage 3: Deduplicator ────────────────────
    content_hash: str | None = None
    duplicate_type: str | None = None
    existing_ticket_id: str | None = None

    # ── Stage 4: Persisted ───────────────────────
    ticket_id: uuid.UUID | None = None
    ticket_status: TicketStatus | None = None
```

---

## Tests

### Unit Tests

---

#### `tests/unit/test_validator.py`

Tests run against `TicketValidator` directly — no DB, no Presidio.

**Normal / positive cases:**

- Valid title + description + priority → `clean_title`, `clean_description` populated correctly
- Leading/trailing whitespace stripped from title
- Internal whitespace runs collapsed
- HTML tags stripped (`<b>error</b>` → `error`)
- HTML attributes stripped (`<span style="color:red">msg</span>` → `msg`)
- All valid priorities (1–5) accepted
- Optional category hint accepted when valid enum value
- Category hint None accepted

**Negative cases:**

- Title shorter than 3 chars after sanitization → `ValidationError` with `detail["field"] == "title"`
- Title longer than 200 chars → `ValidationError`
- Description shorter than 10 chars after sanitization → `ValidationError`
- Description longer than 5000 chars → `ValidationError`
- Priority 0 → `ValidationError`
- Priority 6 → `ValidationError`
- Priority float (2.5) → `ValidationError`
- Invalid category string → `ValidationError`

**Edge cases:**

- Title that becomes too short after HTML stripping → `ValidationError`
- Description containing only whitespace → `ValidationError`
- Description containing only HTML tags (empty after strip) → `ValidationError`
- Unicode content (Japanese/Arabic chars) → passes through unchanged
- Null bytes in input → stripped without error
- Script injection attempt (`<script>alert(1)</script>description`) → tags stripped, text remains

---

#### `tests/unit/test_pii_masker.py`

Tests run against `PIIMasker` directly — Presidio runs locally (no DB).
Mark with `@pytest.mark.slow` since Presidio loads a spaCy model.

**Normal / positive cases:**

- Plain technical text with no PII → returns unchanged, `pii_detected=False`
- Email address → replaced with `<EMAIL_ADDRESS>`, `pii_detected=True`
- Phone number → replaced with `<PHONE_NUMBER>`
- SSN (`123-45-6789`) → replaced with `<US_SSN>`
- Credit card number → replaced with `<CREDIT_CARD>`
- IP address (`192.168.1.1`) → replaced with `<IP_ADDRESS>`
- Person name → replaced with `<PERSON>`
- Mixed PII + technical content → PII masked, technical terms preserved

**Negative cases (resilience):**

- Masker called before `mask()` is invoked — lazy init works
- If Presidio analyzer raises unexpectedly → falls back to original text, `pii_detected=False`, no exception raised

**Edge cases:**

- Empty string input → returns empty string, no error
- Text with only PII → masked to only `<ENTITY_TYPE>` tags
- Multiple occurrences of same PII type → all occurrences masked
- PII inside technical terms (e.g. email embedded in URL) → masked appropriately

---

#### `tests/unit/test_deduplicator.py`

Tests run against `Deduplicator` with mocked `TicketRepository`, `EmbeddingRepository`, and `EmbeddingGenerator` (no DB, no model loading).

**Normal / positive cases:**

- Unique ticket (no exact, no near match) → `is_duplicate=False`, `content_hash` populated
- Exact duplicate (hash match in DB) → `is_duplicate=True`, `duplicate_type="exact"`, `existing_ticket_id` set
- Near duplicate (embedding similarity ≥ 0.95) → `is_duplicate=True`, `duplicate_type="near"`, `existing_ticket_id` set

**Negative cases:**

- Near-duplicate check: similarity score = 0.94 (just below threshold) → NOT flagged as duplicate
- Near-duplicate check: embedding generator raises `EmbeddingError` → near check skipped, ticket treated as unique (no exception)
- Near-duplicate check: embedding repo returns empty list → not a duplicate

**Edge cases:**

- Both exact and near match exist (shouldn't normally happen) → exact match takes priority (checked first)
- Hash computation stability: same title+description always produces same hash regardless of surrounding whitespace
- Different title but identical description → different hash (both title and description are used)
- Dedup window: `get_recent_by_category` called with correct `days` value from settings

---

### Integration Tests

#### `tests/integration/test_ingestion_pipeline.py`

Tests the full `IngestionPipeline.run()` against a real PostgreSQL database.
Uses the `db_session` fixture from `conftest.py` (transaction rollback after each test).

**Happy path:**

- Submit a valid ticket → `IngestionResult` returned with valid `ticket_id` and `status=TicketStatus.NEW`
- Verify ticket row exists in DB with correct fields
- Verify `description` in DB is the masked version (not the raw input)
- Verify `original_description` in DB is the raw input
- Verify `content_hash` is set on the DB row

**PII masking:**

- Ticket description contains an email address → DB row has `pii_detected=True`
- DB `description` field does not contain the original email
- DB `original_description` field contains the original email

**Exact duplicate detection:**

- Submit same ticket twice → second call raises `DuplicateTicketError` with `duplicate_type="exact"`
- DB contains only one ticket row after both calls

**Validation failures:**

- Title too short → `ValidationError` raised, no DB row created
- Description too long → `ValidationError` raised, no DB row created
- Invalid priority → `ValidationError` raised, no DB row created

**Category hint:**

- Submit ticket with `category=TicketCategory.SECURITY` → DB row has `category=SECURITY`
- Submit ticket without category hint → DB row has `category=None`

**Source tracking:**

- Pipeline called with `source=TicketSource.API` → DB row has `source=API`

---

## Reused from Phase 1

| What | Where |
|---|---|
| `TicketRepository.compute_content_hash()` | `src/db/repositories/ticket_repo.py` |
| `TicketRepository.get_by_hash()` | `src/db/repositories/ticket_repo.py` |
| `EmbeddingRepository.find_similar()` | `src/db/repositories/embedding_repo.py` |
| `DuplicateTicketError` | `src/core/exceptions.py` |
| `ValidationError` | `src/core/exceptions.py` |
| `EmbeddingError` | `src/core/exceptions.py` |
| `get_settings()` | `src/core/config.py` — `dedup_similarity_threshold`, `dedup_window_days` |
| `get_logger()` | `src/core/logging.py` |
| `TicketIngestRequest` schema | `src/schemas/ticket.py` |
| `Ticket`, `TicketStatus`, `TicketSource` | `src/db/models.py` |
| `db_session` fixture | `tests/conftest.py` |

---

## Phase 2 Does NOT Include

- `EmbeddingGenerator` implementation (Phase 3) — Deduplicator accepts it as optional, skips near-duplicate check if unavailable
- FastAPI route wiring (Phase 6) — `build_ingestion_pipeline()` factory is defined but not called from any route yet
- Any classification, RAG, or agent logic

---

## Verification

```bash
# Unit tests — no DB or model required
pytest tests/unit/test_validator.py -v
pytest tests/unit/test_pii_masker.py -v -m "not slow"
pytest tests/unit/test_deduplicator.py -v

# Full unit suite
pytest tests/unit/ -v

# Integration tests — requires PostgreSQL
TEST_DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/ticket_routing_test" \
  pytest tests/integration/test_ingestion_pipeline.py -v

# Lint check
ruff check src/ingestion/

# Type check
mypy src/ingestion/
```
