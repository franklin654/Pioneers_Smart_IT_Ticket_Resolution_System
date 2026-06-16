# CLAUDE.md — Full-Stack Engineering Guidelines

This file defines the principles, conventions, and constraints Claude must follow
when generating, reviewing, or refactoring code across the full stack.

- The **`<frontend>`** section applies to React and Angular projects.
- The **`<backend>`** section applies to all server-side frameworks (FastAPI, Spring Boot,
  Node.js/Express, or equivalent).
- Rules in each section apply unless the project's own configuration explicitly overrides them.

---

<!--
  ╔══════════════════════════════════════════════════════════╗
  ║                     FRONTEND SECTION                    ║
  ╚══════════════════════════════════════════════════════════╝
-->

<frontend>

## 1. General Principles

- **Clarity over cleverness.** Write code that a new team member can understand without
  a walkthrough. Prefer explicit over implicit.
- **Single Responsibility.** Every component, service, hook, or module does one thing well.
  If a file is growing beyond ~300 lines, it is a signal to split it.
- **Immutability by default.** Never mutate state or props directly. Always return new
  objects/arrays when updating state.
- **Avoid premature optimisation.** Reach for memoisation (`useMemo`, `useCallback`,
  `ChangeDetectionStrategy.OnPush`) only after profiling reveals a real problem.
- **Consistency beats personal preference.** Follow the conventions already present in the
  codebase. If none exist, establish them in this file.

---

## 2. TypeScript

- **Strict mode is non-negotiable.** Every project must have `"strict": true` in
  `tsconfig.json`.
- **No `any`.** Use `unknown` when the type is genuinely unknown, then narrow it.
  Use precise union types, generics, or utility types (`Partial<T>`, `Pick<T, K>`, etc.).
- **Prefer `interface` for object shapes** shared across files; use `type` for unions,
  intersections, and mapped types.
- **Avoid type assertions (`as X`)** except at API/library boundaries. Document why they
  are necessary with a comment.
- **Enums vs union strings.** Prefer `type Status = 'idle' | 'loading' | 'error'` over
  TypeScript `enum` for simple value sets to avoid runtime overhead.
- **Export types explicitly.** Use `export type { Foo }` so bundlers can tree-shake them.

---

## 3. Project Structure

Keep related code co-located. Group by **feature**, not by technical layer.

```
src/
  features/
    auth/
      components/       # Presentational components for this feature
      hooks/            # (React) Custom hooks
      services/         # (Angular) Injectable services
      store/            # State slices / NgRx feature state
      types.ts          # Feature-local types
      index.ts          # Public API — only export what consumers need
  shared/
    components/         # Generic UI components (Button, Modal, etc.)
    hooks/ | pipes/     # Shared hooks (React) or pipes (Angular)
    utils/              # Pure functions — no side-effects, fully testable
    constants.ts
  app/
    routes.tsx | app-routing.module.ts
    App.tsx | app.component.ts
```

- Each `index.ts` is the **barrel file**; internal implementation files are private.
- Never import from another feature's internal files — only from its `index.ts`.

---

## 4. Component Design

### 4.1 Presentational vs Smart (Container) Components

| | Presentational | Smart / Container |
|---|---|---|
| Receives | Props / `@Input()` | Nothing (pulls from store/service) |
| Emits | Events / `@Output()` | Dispatches actions / calls services |
| Knows about | UI only | Business logic, state, routing |
| Testability | Easy (pure render) | Requires mocks |

- Default to **presentational**; promote to smart only when necessary.
- Smart components should contain minimal template/JSX — delegate rendering to children.

### 4.2 Component Rules

- Components must not exceed **250 lines** (template + logic combined). Refactor if exceeded.
- Accept the **minimum props/inputs** needed to function.
- Avoid boolean prop/input explosion. If a component has `isLarge`, `isPrimary`,
  `isDanger`, `isOutlined` — consolidate into a `variant` type union.
- Never perform data fetching inside a presentational component.
- Default prop values (`defaultProps` in React; `= value` in Angular `@Input()`) must
  be defined for every optional prop.

---

## 5. State Management

- **Local first.** Use component-local state until sharing is proven necessary.
- **Lift state** to the nearest common ancestor before reaching for a global store.
- **Global store** (Redux / Zustand / NgRx / Signals) only for:
  - Data shared across many unrelated components.
  - Data that must survive navigation (user session, cart, notifications).
- Keep store slices **normalised** (no deeply nested objects). Derive UI-specific shapes
  in selectors/computed signals — never in the store itself.
- Side effects belong in middleware (Redux Thunk/Saga), Effects (NgRx), or custom hooks
  — never inside reducers or component lifecycle methods.

---

## 6. Hooks (React-specific)

- Follow the Rules of Hooks unconditionally — no hooks inside conditions or loops.
- Custom hooks must start with `use` and live in their feature's `hooks/` folder.
- A hook that exceeds ~80 lines or has more than 5 `useState` calls should be split.
- Stabilise callbacks with `useCallback` and values with `useMemo` **only when passed to
  memoised children or used in effect dependency arrays** — not by default everywhere.
- Prefer `useReducer` over multiple `useState` calls when state transitions are
  interrelated.
- Cleanup all subscriptions, timers, and event listeners in the `useEffect` return
  function.

---

## 7. Services & Dependency Injection (Angular-specific)

- Services are `providedIn: 'root'` by default unless feature-scoped isolation is
  needed, in which case provide in the feature module / route.
- Services must have a **single purpose** (one service per domain concept: `AuthService`,
  `CartService`, not a catch-all `AppService`).
- All HTTP calls live in a dedicated `*ApiService`; transform responses in a separate
  `*MapperService` or within the observable pipe — not in components.
- Use Angular's `HttpClient` — never raw `fetch` or `XMLHttpRequest`.
- Expose `Observable` from services; subscribe in the smart component or use the
  `async` pipe. Unsubscribe via `takeUntilDestroyed()` or `DestroyRef`.

---

## 8. Styling

- Use a **single styling strategy** per project: CSS Modules, Tailwind utility classes,
  Angular component-scoped styles, or a CSS-in-JS library. Do not mix approaches.
- No inline styles except for dynamic values that cannot be expressed via class names
  (e.g. chart dimensions derived at runtime).
- Define design tokens (colours, spacing, radii, shadows) as CSS custom properties in a
  single `:root` block or Tailwind `theme.extend` — no magic numbers in component styles.
- Class names describing **what a thing is** (`btn-primary`, `card`), not **how it
  looks** (`blue-bg`, `margin-top-16`).
- Media queries use **mobile-first** min-width breakpoints.
- Never use `!important` except to override third-party library styles, with a comment
  explaining why.

---

## 9. Performance

- **Lazy-load routes.** All top-level routes must use dynamic `import()` / Angular
  `loadComponent` / `loadChildren`.
- Images must have explicit `width` and `height` attributes (or `aspect-ratio` CSS) to
  prevent layout shift.
- Use `loading="lazy"` on all below-the-fold `<img>` tags.
- Angular: set `ChangeDetectionStrategy.OnPush` on every new component by default.
- React: wrap lists of expensive items in `React.memo` and provide stable `key` props
  (never array indices for dynamic lists).
- Avoid deriving computed data inside render / template expressions. Cache in selectors,
  computed signals, or `useMemo`.
- Measure before memoising. Use React DevTools Profiler / Angular DevTools to confirm
  savings are real.

---

## 10. Accessibility (a11y)

These are requirements, not suggestions.

- All interactive elements must be focusable and operable by keyboard alone.
- Every `<img>` must have a non-empty `alt` attribute (or `alt=""` if purely decorative).
- Form inputs must have an associated `<label>` (via `for`/`id` or `aria-label`).
- Modals and dialogs must trap focus while open and restore focus to the trigger on close.
- Use semantic HTML (`<button>`, `<nav>`, `<main>`, `<section>`, `<header>`) before
  reaching for `<div>` or `<span>`.
- Colour contrast must meet WCAG 2.1 AA (4.5:1 text, 3:1 UI elements).
- Dynamic content updates must be announced via `aria-live` regions where appropriate.
- Run `axe` or `eslint-plugin-jsx-a11y` as part of the CI lint step.

---

## 11. Error Handling

- **Network errors** must be caught at the service/hook level and converted into typed
  error states — never let raw HTTP errors bubble to the UI.
- Every async operation must expose three states: `loading`, `data`, `error`.
- Use **Error Boundaries** (React) or Angular's `ErrorHandler` to catch unexpected
  runtime errors and display a graceful fallback UI.
- Never swallow errors silently with an empty `catch {}` block. At minimum, log to the
  observability service.
- User-facing error messages must be human-readable. Never expose stack traces,
  internal field names, or HTTP status codes in the UI.

---

## 12. Data Fetching

- Centralise all API base URLs and headers in a single config / interceptor layer.
- **React:** prefer a data-fetching library (React Query / SWR) over hand-rolled
  `useEffect` + `useState` for remote data. This provides caching, deduplication,
  background refresh, and built-in loading/error states.
- **Angular:** use `HttpClient` with RxJS operators; share cache via `shareReplay(1)` on
  long-lived observables.
- Validate API responses at the boundary using a schema library (Zod, io-ts, Yup) before
  the data enters the application.
- Implement request cancellation (AbortController / `takeUntil`) for searches and
  navigation events to prevent stale responses.

---

## 13. Testing

- **Target coverage:** ≥ 80 % for utilities and services; ≥ 70 % for components.
  Coverage alone is not a quality metric — test behaviour, not implementation.
- **Unit tests** cover pure functions, hooks (via `renderHook`), and services (with mocked
  HTTP).
- **Component tests** use Testing Library (`@testing-library/react` or
  `@testing-library/angular`). Query by role and accessible name — never by CSS class or
  test IDs unless no accessible query exists.
- **Integration / E2E tests** (Playwright / Cypress) cover critical user journeys only:
  login, checkout, primary CRUD flows.
- Avoid snapshot tests for logic-heavy components — they assert structure, not behaviour,
  and create noisy diffs.
- Test files live next to the source file they test (`component.spec.ts`). E2E tests live
  in a top-level `e2e/` directory.
- All tests must pass in CI before a PR can be merged.

---

## 14. Code Quality & Linting

- ESLint + Prettier are mandatory. Lint and format on every commit via `lint-staged`.
- Enable these ESLint rule sets as a baseline:
  - `eslint:recommended`
  - `@typescript-eslint/recommended-type-checked`
  - `plugin:react-hooks/recommended` (React)
  - `plugin:@angular-eslint/recommended` (Angular)
  - `plugin:jsx-a11y/recommended` (React)
- **No `console.log` in committed code.** Use a structured logger (`pino`, `loglevel`)
  with log levels controlled by environment.
- Cyclomatic complexity limit: **10** per function. Refactor if exceeded.
- Import order: built-ins → external packages → internal aliases → relative paths.
  Enforced by `eslint-plugin-import` or `perfectionist`.

---

## 15. Security

- **Never store secrets in the frontend.** API keys, tokens, and credentials belong in
  environment variables consumed by the server — not in JS bundles.
- Sanitise any HTML rendered via `dangerouslySetInnerHTML` (React) or `[innerHTML]`
  (Angular) through `DOMPurify` or Angular's built-in `DomSanitizer`.
- Validate and sanitise all user input on the **server**; client-side validation is UX,
  not security.
- Use `Content-Security-Policy` headers — avoid inline scripts and `unsafe-eval`.
- Dependencies must be audited (`npm audit` / `pnpm audit`) in CI. Block on critical
  vulnerabilities.
- Avoid `eval()`, `new Function()`, and dynamic `import()` with user-supplied strings.

---

## 16. Git & Pull Requests

- Branch naming: `feat/<ticket-id>-short-description`, `fix/...`, `chore/...`.
- Commit messages follow **Conventional Commits**:
  `feat(auth): add OAuth2 PKCE flow`, `fix(cart): prevent duplicate item insertion`.
- PRs must:
  - Reference the ticket/issue.
  - Include a brief description of the change and the reasoning.
  - Pass all CI checks (lint, type-check, tests, build).
  - Have at least one reviewer approval before merge.
- Keep PRs small and focused (< 400 lines changed where possible). Large features are
  split into stacked PRs.

---

## 17. Environment Configuration

- Use environment-specific files: `.env.development`, `.env.staging`, `.env.production`.
- All environment variable names must be prefixed with `REACT_APP_` (CRA), `VITE_`
  (Vite), or `NG_APP_` / defined in `environment.ts` files (Angular).
- Document every environment variable in `.env.example` with a description and sample
  value. This file is committed; actual `.env` files are gitignored.
- Feature flags are environment variables or runtime config — never hardcoded `if (env
  === 'production')` blocks scattered across the codebase.

---

## Quick Reference — Frontend

| Situation | Action |
|---|---|
| Adding a new component | Apply single responsibility, TypeScript strict types, accessibility attributes, and a matching `.spec.ts` |
| Adding state | Start local; escalate only if sharing is required |
| Fetching data | Use the established fetching layer; handle all three states (loading / data / error) |
| Writing a utility function | Pure function in `utils/`; unit-tested; no side-effects |
| Touching styles | Use the project's established styling system; no magic numbers |
| Finding a possible perf issue | Profile first, then optimise; add a comment explaining what was measured |
| Encountering `any` | Replace with a precise type or `unknown` + narrowing |

</frontend>

---

<!--
  ╔══════════════════════════════════════════════════════════╗
  ║                      BACKEND SECTION                    ║
  ╚══════════════════════════════════════════════════════════╝
-->

<backend>

## 1. General Principles

- **Correctness before performance.** A fast wrong answer is worse than a slow right one.
  Optimise only after the logic is provably correct.
- **Explicit over implicit.** Prefer code that states its intent directly. Avoid magic,
  metaprogramming, or framework conventions that obscure what is happening.
- **Fail fast.** Validate inputs at the entry point and reject invalid requests
  immediately. Never let bad data propagate deep into the call stack.
- **Determinism.** Given the same inputs, a function must always produce the same output
  (or side-effect). Avoid hidden global state and ambient context.
- **Design for replaceability.** Components should be easy to swap out. Depend on
  abstractions (interfaces/protocols/abstract classes), not concrete implementations.

---

## 2. Project Structure

Organise by **domain / feature**, not by technical role.

```
src/
  <domain>/               # e.g. orders/, users/, payments/
    router.* / controller.*   # HTTP entry points — thin, no business logic
    service.*                 # Orchestrates use-cases; owns transactions
    repository.*              # All DB queries; returns domain objects
    schema.* / dto.*          # Request / response shapes + validation
    model.* / entity.*        # Domain model / ORM entity
    exceptions.* / errors.*   # Domain-specific error types
    <domain>.spec.* / test.*  # Tests co-located with the code they test
  shared/
    middleware/           # Auth, logging, rate-limiting, error handling
    database/             # Connection pool, migration runner, base repository
    config/               # Typed config loaded from environment
    utils/                # Pure helper functions; no dependencies on framework
    types/                # Shared type definitions / interfaces
  main.* / app.*          # Bootstrap and server startup only
```

- No circular imports between domains. If domain A needs something from domain B,
  extract it to `shared/` or introduce a domain event.
- `main.*` / `app.*` must only wire dependencies together — zero business logic.

---

## 3. Layered Architecture

Enforce a strict dependency direction: **Controller → Service → Repository → Database**.
No layer may import from a layer above it.

```
HTTP Request
    │
    ▼
Controller / Router      ← Parses & validates HTTP; delegates; serialises response
    │
    ▼
Service / Use-case       ← Business rules; orchestrates repositories; owns tx boundary
    │
    ▼
Repository / DAO         ← All SQL / ORM queries; returns plain domain objects
    │
    ▼
Database / External API
```

- **Controllers** must be thin: validate input → call one service method → return
  response. No `if/else` business logic, no direct DB access.
- **Services** must not import HTTP primitives (request, response objects).
- **Repositories** must not contain business logic — only data access.
- **Models / Entities** are plain data structures with no HTTP or DB dependencies.

---

## 4. API Design

### 4.1 RESTful Conventions

- Use nouns for resource paths, HTTP verbs for actions:
  `GET /orders`, `POST /orders`, `PATCH /orders/{id}`, `DELETE /orders/{id}`.
- Collections are plural; identifiers are in the path, not the query string.
- Use query parameters for filtering, sorting, and pagination:
  `GET /orders?status=pending&sort=createdAt&page=2&limit=20`.
- Avoid verbs in URLs: prefer `POST /payments/{id}/refund` over
  `POST /refundPayment`.

### 4.2 Versioning

- Version the API from day one: `/api/v1/...`.
- Never make breaking changes within a version. Add a new version for breaking changes
  and deprecate the old one with a sunset date in response headers.

### 4.3 Response Shape

Adopt a consistent envelope and never deviate within a version:

```json
// Success (collection)
{ "data": [...], "meta": { "total": 120, "page": 2, "limit": 20 } }

// Success (single resource)
{ "data": { "id": "...", ... } }

// Error
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable summary.",
    "details": [{ "field": "email", "issue": "Must be a valid email address." }]
  }
}
```

- Never expose internal field names, stack traces, or ORM error messages in responses.
- Always set `Content-Type: application/json` for JSON responses.

### 4.4 HTTP Status Codes

| Situation | Code |
|---|---|
| Successful read | 200 |
| Resource created | 201 + `Location` header |
| No content (delete) | 204 |
| Bad request / validation fail | 400 |
| Unauthenticated | 401 |
| Authenticated but forbidden | 403 |
| Resource not found | 404 |
| Conflict (duplicate, stale) | 409 |
| Unprocessable entity | 422 |
| Rate limited | 429 |
| Server error | 500 |

Never return `200` with an error payload. Never expose a `500` whose body contains a
raw exception message.

---

## 5. Input Validation

- **Validate everything at the boundary** — path params, query params, headers, body.
  Never trust client data inside the service layer.
- Use the framework's native validation mechanism or a dedicated schema library
  (Pydantic, Bean Validation / Hibernate Validator, Zod / Joi / class-validator).
- Validation must be **declarative**, not hand-rolled `if` chains scattered through
  controllers.
- Coerce types explicitly (string → number, string → Date) — do not rely on implicit
  coercion.
- Maximum lengths, allowed characters, and value ranges must be enforced for every
  string and numeric field that enters persistence.
- Reject unknown/extra fields in request bodies (strict / `additionalProperties: false`)
  to prevent mass-assignment vulnerabilities.

---

## 6. Error Handling

- Define a **hierarchy of typed domain exceptions**:
  `NotFoundException`, `ConflictException`, `ForbiddenException`, `ValidationException`.
  These carry a machine-readable `code` and a human-readable `message`.
- A single **global exception handler / error middleware** converts domain exceptions
  to HTTP responses. No controller catches exceptions individually unless it must
  handle them differently.
- **Never swallow exceptions** with an empty `catch` block. At minimum, log and
  re-throw.
- Distinguish **expected errors** (domain exceptions → 4xx) from
  **unexpected errors** (programming bugs, infrastructure failures → 500). Log 500s
  with full stack traces; log 4xx at `warn` level without stack traces.
- Do not propagate raw DB errors (ORMException, `PSQLException`, etc.) to callers.
  Catch them in the repository layer and rethrow as domain exceptions.

---

## 7. Logging & Observability

- Use **structured JSON logging** (not `console.log` / `print`). Every log line is a
  JSON object — never a free-form string with interpolated variables.
- Mandatory fields on every log line:
  `timestamp`, `level`, `service`, `traceId`, `spanId`, `environment`.
- Log levels and when to use them:
  - `DEBUG` — detailed internal state, disabled in production.
  - `INFO` — significant lifecycle events (server started, job completed).
  - `WARN` — recoverable unexpected conditions (retry succeeded, deprecated API used).
  - `ERROR` — failures that need human attention (unexpected exception, integration down).
- Correlate every log line with a **trace ID** injected from the HTTP request header
  (`X-Request-ID` / `traceparent`). Propagate it through all downstream calls.
- Emit **metrics** for: request count, error rate, p50/p95/p99 latency, queue depth,
  active DB connections, cache hit rate.
- Implement a `/health` endpoint (liveness + readiness) and a `/metrics` endpoint
  (Prometheus or equivalent) on every service.

---

## 8. Security

### 8.1 Authentication & Authorisation

- Use short-lived **JWT access tokens** (≤ 15 min) with refresh tokens stored in
  `HttpOnly` cookies or a secure token store — never in `localStorage`.
- Validate the token signature, expiry, issuer (`iss`), and audience (`aud`) on
  every request. Reject if any claim is invalid.
- **Authorisation is a service-layer concern**, not a controller concern. The controller
  checks authentication; the service checks permission for the specific resource.
- Implement **least-privilege**: a token grants only the scopes actually needed.
- Rotate secrets and signing keys via a secrets manager (Vault, AWS Secrets Manager,
  GCP Secret Manager) — never hardcode them.

### 8.2 Injection & Input Safety

- Use **parameterised queries / prepared statements** for all DB access. Never
  concatenate user input into SQL strings.
- Sanitise inputs before passing to shell commands. Prefer library abstractions over
  spawning subprocesses with user-supplied data.
- Escape all data rendered into HTML at the template layer.

### 8.3 Transport & Headers

- Enforce **HTTPS only**. Redirect HTTP → HTTPS at the load-balancer layer.
- Set security headers on every response:
  `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Content-Security-Policy`.
- Enable **CORS** only for known, explicitly listed origins. Never use `*` in
  production.

### 8.4 Secrets & Config

- Secrets must **never** appear in source code, log files, or error messages.
- Load all secrets from environment variables or a secrets manager at startup.
- Audit dependencies for known vulnerabilities as part of CI (`pip audit`, `npm audit`,
  `mvn dependency-check`). Block merges on critical findings.

### 8.5 Rate Limiting & DoS Protection

- Apply rate limiting at the API gateway or reverse-proxy layer for all public
  endpoints.
- Add per-user / per-IP limits on sensitive endpoints (login, password reset,
  token issuance).
- Set request body size limits to prevent large payload attacks.

---

## 9. Database Access

- All DB queries live in the **repository layer** — nowhere else.
- Use the **connection pool** provided by the framework or driver. Never open a new
  connection per request.
- **Transactions** are opened in the service layer and passed into repositories —
  repositories never manage their own transactions.
- Migrations are versioned, incremental, and run automatically at deployment.
  Never edit an already-applied migration; add a new one.
- Add indices for every foreign key and every column used in `WHERE` / `ORDER BY`
  clauses. Verify with `EXPLAIN ANALYZE` before deploying.
- Fetch only the columns you need — avoid `SELECT *` in production code.
- Implement **soft deletes** (`deleted_at` timestamp) for any entity that may need
  audit trails or recovery.
- Set `NOT NULL` constraints, check constraints, and unique constraints at the DB level
  in addition to application-level validation.

---

## 10. Asynchronous Processing & Background Jobs

- Long-running or resource-intensive work (emails, report generation, third-party
  webhooks) must be offloaded to a **message queue or job system** — never block an
  HTTP response for more than ~500 ms.
- Jobs must be **idempotent**: running the same job twice must produce the same result.
  Use idempotency keys for external API calls.
- Implement **retry with exponential back-off and jitter** for all transient failures.
  Define a maximum retry count and a dead-letter queue for poison messages.
- Jobs must record their state (`pending`, `running`, `completed`, `failed`) in
  persistent storage — never in-memory only.
- Publish domain events to the queue; consumers must not assume ordering unless the
  queue guarantees it (FIFO).
- Always set a **timeout** on external HTTP calls made from jobs. Treat no response
  within the timeout as an error.

---

## 11. Performance

- Target **< 100 ms** for simple CRUD endpoints and **< 300 ms** for complex
  aggregations under realistic load. Investigate anything slower.
- Cache aggressively at the right layer:
  - **In-process cache** for static config and lookup tables that change rarely.
  - **Distributed cache** (Redis / Memcached) for session data and frequently-read
    aggregates.
  - **HTTP cache headers** (`Cache-Control`, `ETag`) for public read-only resources.
- Cache invalidation must be explicit and documented. Prefer **write-through** or
  **event-driven invalidation** over TTL-only strategies for mutable data.
- Use **pagination** for every endpoint that can return more than one record. Never
  return unbounded lists.
- Profile DB queries in the performance test environment before production. Use `EXPLAIN`
  to confirm index usage.
- Use **connection pooling** and **keep-alive** for all outbound HTTP calls to external
  services.

---

## 12. Testing

### 12.1 Test Pyramid

- **Unit tests** (majority): pure functions, domain logic, service methods with
  mocked repositories. Fast, no I/O.
- **Integration tests**: service + real DB (test database / test containers). Test
  that queries work, transactions commit and roll back correctly.
- **Contract / API tests**: test the HTTP layer with a real server against a fixed
  request/response contract (Pact, or plain HTTP client against a test instance).
- **E2E tests** (minority): critical happy paths only against a staging environment.

### 12.2 Coverage & Quality

- Target ≥ 80 % line coverage for service and utility layers.
- Coverage is a floor, not a goal. A test that asserts `response.status == 200` without
  checking the payload is worthless noise.
- Every bug fix must be accompanied by a failing test that reproduces the bug before
  the fix is applied.
- Tests must be **independent** — no shared mutable state between tests. Each test
  sets up and tears down its own data.
- Use **test factories / builders** (not hard-coded fixtures) to construct test data.
  This keeps tests readable and resilient to schema changes.

### 12.3 What to Test

| Layer | Test focus |
|---|---|
| Utils / helpers | Pure function in / out, edge cases |
| Service | Business rules, error paths, transaction rollback |
| Repository | Query correctness, index usage (integration) |
| Controller | Request parsing, validation rejection, response shape |
| Auth middleware | Valid token, expired token, wrong scope |
| Background jobs | Idempotency, retry behaviour, failure state |

---

## 13. Configuration Management

- **Zero configuration in code.** All environment-specific values (DB URLs, API keys,
  feature flags, timeouts, pool sizes) come from environment variables.
- Validate and **type the config at startup**. If a required variable is missing or
  malformed, the process must refuse to start with a clear error message.
- Keep a `.env.example` file committed to the repo documenting every variable with a
  description and a safe sample value. Never commit real `.env` files.
- Group config into namespaced objects (`config.database.poolSize`) rather than a flat
  bag of variables.
- Feature flags that control business behaviour live in a dedicated flag system
  (LaunchDarkly, Unleash, or a simple DB-backed table) — not as boolean environment
  variables scattered across the codebase.

---

## 14. Dependency Management

- Pin direct dependencies to an **exact version** in the lock file
  (`package-lock.json`, `poetry.lock`, `pom.xml`).
- Review all new dependencies before adding them. Consider: maintenance status, licence,
  size, and whether the problem could be solved with stdlib.
- Run `audit` checks in CI and fail on high/critical findings.
- Prefer **one library per concern**: one HTTP client, one validation library, one ORM.
  Avoid having two libraries solving the same problem.
- Remove unused dependencies regularly (`depcheck`, `pip-autoremove`).

---

## 15. Documentation

- Every **public API endpoint** must be documented in OpenAPI / Swagger, including all
  request parameters, response shapes, and error codes. Generate this from code
  annotations — do not maintain a separate YAML file by hand.
- Every **service method** with non-obvious behaviour must have an inline comment
  explaining *why*, not *what*. The code expresses what; comments explain business
  rationale.
- Architecture decision records (ADRs) live in `docs/adr/` and explain significant
  technical choices and the alternatives considered.
- `README.md` at the project root must cover: local setup, environment variables
  required, how to run tests, and how to run migrations.

---

## 16. Code Quality & Linting

- Linters and formatters run on every commit via pre-commit hooks and in CI.
  PRs with lint failures are not merged.
- Baseline linting tools per ecosystem:

  | Ecosystem | Linter | Formatter |
  |---|---|---|
  | Node.js | ESLint + `@typescript-eslint` | Prettier |
  | Python | Ruff (or Flake8 + isort) | Black |
  | Java / Kotlin | Checkstyle / ktlint | google-java-format |

- **Cyclomatic complexity limit: 10** per function. Refactor into smaller units if
  exceeded.
- **No commented-out code** in committed files. Delete it — version control preserves
  history.
- **No `TODO` / `FIXME` in committed code** unless linked to a tracked issue:
  `// TODO(#1234): Remove after migration completes`.
- Function argument limit: **4 parameters**. Beyond that, group into a typed
  request/options object.

---

## 17. Git & Pull Requests

- Branch naming: `feat/<ticket-id>-short-description`, `fix/...`, `chore/...`,
  `hotfix/...`.
- Commit messages follow **Conventional Commits**:
  `feat(orders): add bulk cancellation endpoint`,
  `fix(auth): prevent token reuse after logout`.
- Every PR must:
  - Reference the ticket / issue.
  - Include a description of *what* changed and *why*.
  - Pass all CI checks (lint, type-check, tests, security audit, build).
  - Have at least one reviewer approval.
- Keep PRs **small and focused** (< 400 lines where possible). Database migrations and
  the code that uses them ship in the same PR.
- **Never force-push to `main` / `master` / `develop`.**

---

## 18. Resilience & Operational Readiness

- Implement **graceful shutdown**: on `SIGTERM`, stop accepting new requests, finish
  in-flight requests (with a timeout), close DB connections, then exit.
- Set **timeouts** on every outbound call: DB queries, HTTP clients, queue consumers.
  Nothing should block indefinitely.
- Use the **Circuit Breaker** pattern for calls to external services that may be
  unavailable. Open the circuit after N consecutive failures; half-open after a
  cooldown period.
- Design for **horizontal scaling**: no local state (sessions, files) on the application
  server. All shared state belongs in a distributed store.
- Implement **idempotency keys** for any endpoint that triggers a side-effect
  (payment, email send) so clients can safely retry on network failure.
- Document the **runbook** for every background job and cron task: what it does, how
  often, how to manually trigger it, and what to do if it fails.

---

## Quick Reference — Backend

| Situation | Action |
|---|---|
| Adding an endpoint | Validate input at the boundary; delegate to service; return typed response |
| Writing a service method | No HTTP primitives; typed domain exceptions; single responsibility |
| Writing a query | Repository layer only; parameterised; fetch minimal columns; check index |
| Handling an error | Typed exception + global handler; log with trace ID; never expose internals |
| Adding config | Environment variable; validate at startup; document in `.env.example` |
| Adding a dependency | Check maintenance status, licence, and audit findings first |
| Writing a test | Test behaviour not implementation; independent; uses factories not fixtures |
| Touching auth | Validate all token claims; authorise in service, not controller |
| Any async/background work | Idempotent; retryable; state persisted; dead-letter queue defined |
| A function grows beyond 40 lines | Stop and ask: can this be split into smaller functions? |

</backend>

---

*Amend this file via PR with team discussion. Do not override conventions unilaterally.
The goal is a codebase where every file looks like it was written by one careful engineer.*
