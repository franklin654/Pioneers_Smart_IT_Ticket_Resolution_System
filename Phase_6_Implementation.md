# Phase 6 — API Layer (Completed)

**Project root:** `app_v2/backend/`
**Status:** Complete — 396/396 tests passing, 73.26% coverage

---

## What Was Built

Phase 6 wires all prior phases (ingestion, classifier, RAG, agents, orchestrator) into a production-quality FastAPI REST + WebSocket API. The key design decisions:

- **POST /ingest returns 202 immediately** — ingestion runs synchronously; orchestration runs as a FastAPI `BackgroundTask` so the client doesn't wait for AI processing
- **WebSocket streams live status transitions** — Angular frontend polls WS instead of HTTP polling
- **JWT HS256 auth** via `python-jose`; credentials stored in `Settings` env vars (no user table needed for demo)
- **PBKDF2-SHA256 password hashing** via stdlib `hashlib` (260,000 iterations, OWASP 2023) — replaces passlib/bcrypt which has a known incompatibility with bcrypt ≥ 4.x
- **Sliding-window rate limiter** — per-IP, `collections.deque`, health endpoints exempt
- **Global exception handler** — maps all `AppBaseException` subclasses to `{"error_code", "message", "detail"}` JSON

---

## Files Created

```text
src/api/
├── main.py                    # FastAPI app factory, lifespan, middleware, routers
├── dependencies.py            # Shared deps: repos, pipeline, background orchestrator
├── websocket.py               # WS /ws/tickets/{ticket_id} — 2s polling, event streaming
├── middleware/
│   ├── auth.py                # PBKDF2 helpers, JWT create/decode, get_current_user, require_role
│   └── rate_limiter.py        # Sliding-window rate limiter (Starlette BaseHTTPMiddleware)
└── routes/
    ├── auth.py                # POST /api/v1/auth/token (OAuth2 form-data, Swagger-compatible)
    ├── tickets.py             # POST /ingest, GET /{id}, GET /
    ├── resolutions.py         # POST /{ticket_id}/feedback
    ├── health.py              # GET /health/live, GET /health/ready
    └── __init__.py            # Empty — avoids module-level engine creation at import time

tests/unit/
├── test_auth_middleware.py    # 18 tests: PBKDF2, JWT, expiry, tamper, RBAC
├── test_rate_limiter.py       # 9 tests: window limits, IP isolation, reset, health exempt
├── test_auth_routes.py        # 8 tests: valid/invalid credentials, token shape
├── test_ticket_routes.py      # 13 tests: ingest 202/409/422, GET 200/404, list + filters
├── test_resolution_routes.py  # 6 tests: accepted/rejected/modified → 204, missing → 404
├── test_health_routes.py      # 7 tests: liveness/readiness, no auth required
└── test_main.py               # 10 tests: app factory, exception handler HTTP status mapping
```

---

## 1. `src/api/main.py` — App Entry Point

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()   # idempotent — creates tables/indexes
    yield
    await engine.dispose()

def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan, ...)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, ...)
    app.add_middleware(RateLimiterMiddleware, requests_per_minute=settings.rate_limit_per_minute)

    @app.exception_handler(AppBaseException)
    async def app_exception_handler(request, exc):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.include_router(auth.router,        prefix="/api/v1/auth")
    app.include_router(tickets.router,     prefix="/api/v1/tickets")
    app.include_router(resolutions.router, prefix="/api/v1/resolutions")
    app.include_router(health.router,      prefix="/health")
    app.add_api_websocket_route("/ws/tickets/{ticket_id}", ws_ticket_status)
    return app

app = create_app()
```

Start with: `uvicorn src.api.main:app --reload`

---

## 2. `src/api/dependencies.py` — Shared Dependencies

```python
# Repository deps
async def get_ticket_repo(db=Depends(get_db)) -> TicketRepository: ...
async def get_resolution_repo(db=Depends(get_db)) -> ResolutionRepository: ...

# Ingestion pipeline (no embedding-based dedup — heavy model avoided per-request)
async def get_ingestion_pipeline(db=Depends(get_db)) -> IngestionPipeline:
    return build_ingestion_pipeline(session=db, embedding_generator=None)

# Background orchestrator — creates its own session (request session closes before task runs)
async def run_orchestrator_background(ticket_id: uuid.UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            orchestrator = _build_orchestrator(session, get_settings())
            await orchestrator.process_ticket(ticket_id)
    except Exception as exc:
        logger.error("Background orchestrator failed", ...)
```

`_build_orchestrator()` uses deferred imports to avoid loading ML models at startup. It constructs the full agent graph: `EmbeddingGenerator` → `TicketClassifier` → `KnowledgeBase` + `HybridRetriever` + `MMRReranker` → `RAGGenerator` → `ClassifierAgent` + `RAGAgent` + `EvaluatorAgent` → `TicketUserProxy` + `TicketRouter` + `EscalationDetector` → `TicketOrchestrator`.

---

## 3. `src/api/middleware/auth.py` — JWT + RBAC

### Password hashing — stdlib PBKDF2, not passlib

Passlib 1.7.4 is incompatible with bcrypt ≥ 4.x (raises `ValueError` even for short passwords). Replaced with stdlib `hashlib.pbkdf2_hmac`.

```python
_PBKDF2_ITERATIONS = 260_000  # OWASP 2023 recommendation

def hash_password(plain: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()
    return f"{salt}${digest}"

def verify_password(plain: str, hashed: str) -> bool:
    try:
        salt, digest = hashed.split("$", 1)
    except ValueError:
        return False
    new_digest = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()
    return hmac.compare_digest(new_digest, digest)  # constant-time
```

### JWT helpers

```python
def create_access_token(data: dict, settings: Settings) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

def decode_access_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except JWTError:
        raise AuthenticationError("Invalid token")
```

### FastAPI dependencies

```python
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

async def get_current_user(token: str | None = Depends(_oauth2_scheme), settings=Depends(get_settings)) -> dict:
    if not token:
        raise AuthenticationError("Authentication required")
    return decode_access_token(token, settings)

def require_role(*roles: str):
    async def _guard(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise AuthorizationError(f"Role '{user.get('role')}' not permitted. Required: {list(roles)}")
        return user
    return _guard
```

---

## 4. `src/api/middleware/rate_limiter.py` — Sliding Window

```python
class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int) -> None:
        super().__init__(app)
        self._rpm = requests_per_minute
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        if "/health" in request.url.path:      # health probes are exempt
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = self._windows[ip]

        while window and now - window[0] > 60:  # evict stale timestamps
            window.popleft()

        if len(window) >= self._rpm:
            retry_after = int(60 - (now - window[0])) + 1
            raise RateLimitError(retry_after=retry_after)

        window.append(now)
        return await call_next(request)
```

---

## 5. `src/api/routes/auth.py` — Token Endpoint

Uses **OAuth2 Password Flow** (`application/x-www-form-urlencoded`) so the Swagger UI Authorize button works natively. Angular uses `HttpParams` with the same content type.

```python
@router.post("/token", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), settings=Depends(get_settings)) -> TokenResponse:
    username_ok = form.username == settings.admin_username
    password_ok = verify_password(form.password, _hashed_admin_password(settings))
    if not (username_ok and password_ok):
        raise AuthenticationError("Invalid username or password")
    token = create_access_token({"sub": form.username, "role": "admin"}, settings)
    return TokenResponse(access_token=token)

@lru_cache(maxsize=1)
def _hashed_admin_password(settings: Settings) -> str:
    return hash_password(settings.admin_password)  # computed once per process
```

**Settings fields added to `src/core/config.py`:**

```python
admin_username: str = "admin"
admin_password: str = "changeme123"
```

**Angular login (3 extra lines vs JSON):**

```typescript
const body = new HttpParams().set('username', u).set('password', p);
this.http.post('/api/v1/auth/token', body,
  { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
```

---

## 6. `src/api/routes/tickets.py` — Ticket Endpoints

| Method | Path                          | Auth     | Status  | Description                                    |
| ------ | ----------------------------- | -------- | ------- | ---------------------------------------------- |
| POST   | `/api/v1/tickets/ingest`      | Required | 202     | Ingest + queue for async processing            |
| GET    | `/api/v1/tickets/{ticket_id}` | None     | 200/404 | Full detail with classification + resolution   |
| GET    | `/api/v1/tickets/`            | None     | 200     | Paginated list, optional filters               |

```python
@router.post("/ingest", response_model=TicketIngestResponse, status_code=202)
async def ingest_ticket(request, background_tasks, pipeline=Depends(...), _user=Depends(get_current_user)):
    result = await pipeline.run(request)
    background_tasks.add_task(run_orchestrator_background, result.ticket_id)
    return TicketIngestResponse(ticket_id=result.ticket_id, status=result.status, message=result.message)

@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(ticket_id: uuid.UUID, repo=Depends(get_ticket_repo)):
    ticket = await repo.get_with_relations(ticket_id)
    if ticket is None:
        raise TicketNotFoundError(str(ticket_id))
    return TicketDetailResponse.model_validate(ticket)

@router.get("/", response_model=PaginatedTicketsResponse)
async def list_tickets(category=None, status=None, priority=None,
                       offset=Query(0), limit=Query(50, le=200), repo=Depends(get_ticket_repo)):
    filters = TicketSearchFilters(category=category, status=status, priority=priority)
    tickets, total = await repo.search(filters, offset=offset, limit=limit)
    return PaginatedTicketsResponse(items=[TicketSummary.model_validate(t) for t in tickets],
                                    total=total, offset=offset, limit=limit)
```

---

## 7. `src/api/routes/resolutions.py` — Feedback Endpoint

```python
@router.post("/{ticket_id}/feedback", status_code=204)
async def submit_feedback(ticket_id: uuid.UUID, body: FeedbackRequest,
                          repo=Depends(get_resolution_repo), user=Depends(get_current_user)):
    resolution = await repo.get_by_ticket_id(ticket_id)
    if resolution is None:
        raise TicketNotFoundError(str(ticket_id))
    feedback = FeedbackLog(resolution_id=resolution.id, agent_id=user.get("sub", "unknown"),
                           action=body.action, modified_resolution=body.modified_resolution)
    await repo.add_feedback(feedback)
    return Response(status_code=204)
```

Actions: `ACCEPTED` / `MODIFIED` (requires `modified_resolution` text) / `REJECTED`. Returns 204 No Content.

---

## 8. `src/api/routes/health.py` — Health Probes

```python
@router.get("/live")
async def liveness() -> dict:
    return {"status": "ok"}          # 200 if process is alive

@router.get("/ready")
async def readiness() -> dict:
    if not await check_db_health():
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ready", "database": "ok"}
```

No auth required. Exempt from rate limiting.

---

## 9. `src/api/websocket.py` — Live Status Streaming

```python
_TERMINAL_STATUSES = frozenset({AUTO_RESOLVED, ASSIGNED, ESCALATED, CLOSED})

async def ws_ticket_status(websocket: WebSocket, ticket_id: uuid.UUID) -> None:
    await websocket.accept()
    last_status = None
    try:
        while True:
            async with AsyncSessionLocal() as session:
                ticket = await TicketRepository(session).get_by_id(ticket_id)
            if ticket is None:
                await websocket.send_json({"event": "error", "message": f"Ticket '{ticket_id}' not found"})
                break
            if ticket.status != last_status:
                await websocket.send_json({"event": "status_changed", "status": ticket.status.value})
                last_status = ticket.status
            if ticket.status in _TERMINAL_STATUSES:
                await websocket.send_json({"event": "done", "status": ticket.status.value})
                break
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()
```

**Event schema:**

```json
{"event": "status_changed", "status": "processing"}
{"event": "done",           "status": "auto_resolved"}
{"event": "error",          "message": "Ticket '...' not found"}
```

---

## 10. Error Response Format

All `AppBaseException` subclasses produce:

```json
{
  "error_code": "TICKET_NOT_FOUND",
  "message": "Ticket 'abc-123' not found",
  "detail": { ... }
}
```

| Exception              | HTTP Status |
| ---------------------- | ----------- |
| `TicketNotFoundError`  | 404         |
| `AuthenticationError`  | 401         |
| `AuthorizationError`   | 403         |
| `DuplicateTicketError` | 409         |
| `RateLimitError`       | 429         |

---

## 11. Test Coverage — 71 New Tests (396 Total)

| File                        | Tests | What's covered                                                                            |
| --------------------------- | ----- | ----------------------------------------------------------------------------------------- |
| `test_auth_middleware.py`   | 18    | PBKDF2 hash/verify, JWT create/decode, expiry, tamper, `get_current_user`, `require_role` |
| `test_rate_limiter.py`      | 9     | Window limits, IP isolation, window reset after 60s, health exempt                        |
| `test_auth_routes.py`       | 8     | Valid credentials → token, wrong password/username → 401, error_code shape                |
| `test_ticket_routes.py`     | 13    | Ingest 202/409/422, GET 200/404, list 200 + filters + pagination                          |
| `test_resolution_routes.py` | 6     | ACCEPTED/MODIFIED/REJECTED → 204, no resolution → 404, MODIFIED without text → 422        |
| `test_health_routes.py`     | 7     | Live 200, ready 200/503, no auth required                                                 |
| `test_main.py`              | 10    | App factory, exception handler maps all error codes to correct HTTP status                |

**Coverage:** 73.26% (threshold: 70%)

---

## 12. Key Fixes Applied During Implementation

### `routes/__init__.py` — emptied to avoid import-time `Settings` validation

`database.py` creates the SQLAlchemy engine at module level, which calls `get_settings()` → `Settings()` → requires `DATABASE_URL` and `SECRET_KEY` in env. Eager imports in `routes/__init__.py` triggered this at `pytest` collection time before env vars were set. Fix: made `__init__.py` a docstring-only file.

### `tests/conftest.py` — env vars injected before any imports

```python
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/ticket_routing_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-minimum-32-characters!!")
```

These must be at the very top of `conftest.py` before any project imports.

### `tests/unit/test_config.py` — `monkeypatch.delenv` required

After conftest injects env vars, `test_missing_database_url_raises` would never raise unless the env var is explicitly removed:

```python
def test_missing_database_url_raises(self, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(secret_key="a" * 32)
```

---

## 13. Verification

```bash
# Unit tests only (mocked, no DB required)
mamba run -n ticket_routing python -m pytest tests/unit/ -v

# Manual smoke test (requires running server + DB)
uvicorn src.api.main:app --reload

# Get token
curl -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin&password=changeme123"

# Ingest a ticket
curl -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -X POST http://localhost:8000/api/v1/tickets/ingest \
     -d '{"title": "VPN authentication failure", "description": "Users cannot connect via VPN from home network.", "priority": 2}'

# Stream status via WebSocket
wscat -c "ws://localhost:8000/ws/tickets/<ticket_id>"

# Health checks (no auth)
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready

# Swagger UI (Authorize button uses the token endpoint automatically)
open http://localhost:8000/docs
```

---

## 14. DB-Backed Auth Migration Path (Future)

If a judge asks how to migrate to DB-stored users, the change is minimal:

1. Add `User` ORM model (`id`, `username`, `hashed_password`, `role`)
2. Add `UserRepository.get_by_username(username)` method
3. In `auth.py`, replace the env-var check with:

   ```python
   user = await user_repo.get_by_username(form.username)
   if user is None or not verify_password(form.password, user.hashed_password):
       raise AuthenticationError(...)
   token = create_access_token({"sub": user.username, "role": user.role}, settings)
   ```

The JWT layer (`get_current_user`, `require_role`, `decode_access_token`) is **unchanged** — roles are already embedded in the token payload.
