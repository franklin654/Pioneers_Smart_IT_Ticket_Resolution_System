# Phase 7 — Angular 20 Frontend

**Project root:** `app_v2/frontend/`
**Builds on:** Phase 6 complete (FastAPI REST + WebSocket API fully operational, 396 tests passing)

---

## Context

The backend exposes a complete API surface (Phases 1–6). Phase 7 builds the Angular 20 SPA that judges and users interact with. The `frontend/` directory is currently empty; Docker Compose already has the service defined at port 4200:80 (expects a Dockerfile in `../frontend`). The plan uses Angular 20 conventions throughout: standalone components, signals, `inject()`, new control flow syntax (`@if`/`@for`/`@switch`), and functional interceptors/guards.

---

## Files to Create

```text
frontend/
├── Dockerfile                          # Multi-stage: Node 22 build → nginx alpine serve
├── nginx.conf                          # SPA fallback + /api + /ws proxy to backend
├── .dockerignore
├── angular.json
├── package.json
├── tsconfig.json
├── tsconfig.app.json
└── src/
    ├── index.html
    ├── main.ts
    ├── styles.scss                     # Global Material theme
    ├── environments/
    │   ├── environment.ts              # dev: apiUrl='http://localhost:8000', wsUrl='ws://localhost:8000'
    │   └── environment.prod.ts         # prod: apiUrl='', wsUrl='' (nginx proxies /api and /ws)
    └── app/
        ├── app.config.ts               # provideRouter, provideHttpClient, provideAnimationsAsync
        ├── app.routes.ts               # Route definitions (all lazy-loaded)
        ├── app.component.ts/html/scss  # Shell: mat-toolbar nav + router-outlet
        ├── core/
        │   ├── models/
        │   │   └── ticket.models.ts    # All TS interfaces + enum types matching backend schemas
        │   ├── services/
        │   │   ├── auth.service.ts
        │   │   ├── ticket.service.ts
        │   │   ├── websocket.service.ts
        │   │   └── dashboard.service.ts
        │   ├── interceptors/
        │   │   └── auth.interceptor.ts # HttpInterceptorFn — adds Bearer header
        │   └── guards/
        │       └── auth.guard.ts       # CanActivateFn — redirects to /login if unauthenticated
        ├── features/
        │   ├── login/
        │   │   └── login.component.ts/html/scss
        │   ├── ticket-submit/
        │   │   └── ticket-submit.component.ts/html/scss
        │   ├── ticket-status/
        │   │   ├── ticket-status.component.ts/html/scss
        │   │   ├── classification-card/classification-card.component.ts/html/scss
        │   │   ├── resolution-card/resolution-card.component.ts/html/scss
        │   │   └── feedback-panel/feedback-panel.component.ts/html/scss
        │   └── dashboard/
        │       ├── dashboard.component.ts/html/scss
        │       └── category-chart/category-chart.component.ts/html/scss
        └── shared/
            ├── components/
            │   ├── status-badge/status-badge.component.ts/html
            │   ├── priority-chip/priority-chip.component.ts/html
            │   └── star-rating/star-rating.component.ts/html
            └── pipes/
                ├── category-label.pipe.ts
                └── priority-label.pipe.ts
```

---

## 0. Styling Strategy — Single Source of Truth

**One styling system only: Angular Material SCSS theming + component-scoped SCSS.**

No Tailwind, no utility CSS library, no CDN stylesheets. Mixing Tailwind with Material causes selector specificity conflicts, leftover config files (`tailwind.config.js`, `postcss.config.js`), and drift between component SCSS and utility classes across commits.

### Rules (enforced throughout implementation):

1. **Global styles only in `src/styles.scss`** — Material theme setup (`@use '@angular/material'`), CSS custom properties (`--color-primary` etc.), and 3-5 utility classes maximum (`.spacer`, `.pii-banner`, `.page-container`).
2. **Component styles only in `<component>.component.scss`** — scoped to that component via Angular's ViewEncapsulation. No leaking global selectors.
3. **Material components for all UI elements** — `mat-card`, `mat-button`, `mat-chip`, `mat-form-field` etc. Do NOT replicate their look with custom CSS.
4. **No `styleUrls` pointing to shared/global files** — each component references only its own `.scss`.
5. **No inline `style=""` attributes** — all presentation via SCSS classes.
6. **No leftover config files** — this project will have zero `tailwind.config.*`, `postcss.config.*`, or `critters.config.*` files.

### File ownership:

| File | Purpose |
|---|---|
| `src/styles.scss` | Material theme `@include`, 3-5 global utility classes only |
| `*.component.scss` | Component-specific layout, spacing, overrides |
| No other `.css`/`.scss` files | — |

### `src/styles.scss` structure (to follow exactly):

```scss
@use '@angular/material' as mat;

@include mat.core();

$primary: mat.define-palette(mat.$indigo-palette);
$accent:  mat.define-palette(mat.$amber-palette, A200, A100, A400);
$warn:    mat.define-palette(mat.$red-palette);

$theme: mat.define-light-theme((
  color:      (primary: $primary, accent: $accent, warn: $warn),
  typography: mat.define-typography-config(),
  density:    0,
));

@include mat.all-component-themes($theme);

html, body { height: 100%; margin: 0; font-family: Roboto, 'Helvetica Neue', sans-serif; }

// ── 5 global utilities — nothing else goes here ────────────────────────────
.spacer         { flex: 1 1 auto; }
.page-container { padding: 24px; max-width: 1200px; margin: 0 auto; }
.pii-banner     { background: #fff3e0; border-left: 4px solid #ff9800; padding: 12px 16px; margin-bottom: 16px; }
.kpi-row        { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
.full-width     { width: 100%; }
```

This is the complete `styles.scss`. Nothing is added to it during feature implementation — all feature styles go in the component's own `.scss`.

---

## 1. TypeScript Models (`core/models/ticket.models.ts`)

Mirror backend schemas exactly:

```typescript
export type TicketCategory = 'infrastructure'|'application'|'security'|'database'|'access_management'|'network';
export type TicketStatus   = 'new'|'classifying'|'classified'|'retrieving'|'generating'|'evaluating'|'auto_resolved'|'assigned'|'escalated'|'closed'|'reopened';
export type ConfidenceLevel = 'high'|'medium'|'low';
export type RoutingDecision = 'auto_resolved'|'assigned'|'escalated';
export type FeedbackAction  = 'accepted'|'modified'|'rejected';

export const PIPELINE_STEPS: TicketStatus[] = [
  'new','classifying','classified','retrieving','generating','evaluating',
  'auto_resolved','assigned','escalated','closed','reopened'
];
export const TERMINAL_STATUSES: TicketStatus[] = ['auto_resolved','assigned','escalated','closed'];

export interface CategoryProbability    { category: TicketCategory; probability: number; }
export interface RetrievedTicketRef     { ticket_id: string; title: string; similarity_score: number; }
export interface ClassificationResponse { predicted_category: TicketCategory; confidence: number; confidence_level: ConfidenceLevel; top_categories: CategoryProbability[]; is_multi_domain: boolean; classification_method: string; }
export interface ResolutionResponse     { id: string; suggested_steps: string|null; retrieved_tickets: RetrievedTicketRef[]|null; llm_quality_score: number|null; routing_decision: RoutingDecision; assigned_department: string|null; escalation_reason: string|null; is_repeated_issue: boolean; }
export interface TicketDetailResponse   { id: string; title: string; description: string; category: TicketCategory|null; priority: number; status: TicketStatus; source: string; pii_detected: boolean; created_at: string; updated_at: string; classification: ClassificationResponse|null; resolution: ResolutionResponse|null; }
export interface TicketSummary          { id: string; title: string; category: TicketCategory|null; priority: number; status: TicketStatus; created_at: string; }
export interface PaginatedTicketsResponse { items: TicketSummary[]; total: number; offset: number; limit: number; }
export interface TicketIngestRequest    { title: string; description: string; priority: number; category?: TicketCategory; }
export interface TicketIngestResponse   { ticket_id: string; status: TicketStatus; message: string; }
export interface FeedbackRequest        { action: FeedbackAction; modified_resolution?: string; }
export interface ApiError               { error_code: string; message: string; detail: Record<string,unknown>; }
export type WsEvent =
  | { event: 'status_changed'; status: TicketStatus }
  | { event: 'done';           status: TicketStatus }
  | { event: 'error';          message: string };
```

---

## 2. Services

### `AuthService`
- `token = signal<string|null>(localStorage.getItem('jwt'))` — initialized from storage
- `isAuthenticated = computed(() => this.token() !== null)`
- `login(username, password): Observable<void>` → `POST /api/v1/auth/token` as `application/x-www-form-urlencoded` → store `access_token` in localStorage, update signal
- `logout()` → clear localStorage, `token.set(null)`

### `TicketService`
- `ingest(req)` → `POST /api/v1/tickets/ingest`
- `getTicket(id)` → `GET /api/v1/tickets/{id}`
- `listTickets(params?)` → `GET /api/v1/tickets/` with `HttpParams`
- `submitFeedback(ticketId, req)` → `POST /api/v1/resolutions/{ticketId}/feedback` (204 → void)

### `WebSocketService`
Returns a cold `Observable<WsEvent>` — opens on subscribe, closes on unsubscribe or terminal:

```typescript
connect(ticketId: string): Observable<WsEvent> {
  return new Observable<WsEvent>(observer => {
    const url = environment.wsUrl
      ? `${environment.wsUrl}/ws/tickets/${ticketId}`
      : `ws://${window.location.host}/ws/tickets/${ticketId}`;
    const ws = new WebSocket(url);
    ws.onmessage = msg => observer.next(JSON.parse(msg.data));
    ws.onerror   = err => observer.error(err);
    ws.onclose   = ()  => observer.complete();
    return () => { if (ws.readyState === WebSocket.OPEN) ws.close(); };
  }).pipe(takeWhile(ev => ev.event !== 'done', true));
}
```

### `DashboardService`
- `getRecentTickets()` → `GET /api/v1/tickets/?limit=100`
- `computeKpis(items: TicketSummary[])` → `{ total, autoResolveRate, escalationRate }` (avg LLM quality shown as N/A — not in TicketSummary)

---

## 3. HTTP Interceptor (Functional, Angular 20)

```typescript
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const token = inject(AuthService).token();
  if (token) return next(req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }));
  return next(req);
};
```

Registered in `app.config.ts` as `provideHttpClient(withFetch(), withInterceptors([authInterceptor]))`.

---

## 4. Route Guard (Functional)

```typescript
export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.isAuthenticated() || inject(Router).createUrlTree(['/login']);
};
```

---

## 5. Routing (`app.routes.ts`)

```typescript
export const routes: Routes = [
  { path: '',            redirectTo: '/dashboard', pathMatch: 'full' },
  { path: 'login',       loadComponent: () => import('./features/login/login.component').then(m => m.LoginComponent) },
  { path: 'submit',      loadComponent: () => import('./features/ticket-submit/ticket-submit.component').then(m => m.TicketSubmitComponent), canActivate: [authGuard] },
  { path: 'tickets/:id', loadComponent: () => import('./features/ticket-status/ticket-status.component').then(m => m.TicketStatusComponent) },
  { path: 'dashboard',   loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent) },
  { path: '**',          redirectTo: '/dashboard' },
];
```

`withComponentInputBinding()` in app.config.ts lets `:id` bind directly to `@Input() id!: string`.

---

## 6. `app.config.ts`

```typescript
export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withFetch(), withInterceptors([authInterceptor])),
    provideAnimationsAsync(),
  ]
};
```

---

## 7. Component Designs

### `AppComponent` (shell)
```html
<mat-toolbar color="primary">
  <a mat-button routerLink="/dashboard">TicketIQ</a>
  <span class="spacer"></span>
  <a mat-button routerLink="/dashboard">Dashboard</a>
  @if (authService.isAuthenticated()) {
    <a mat-button routerLink="/submit">Submit Ticket</a>
    <button mat-button (click)="authService.logout()">Logout</button>
  } @else {
    <a mat-button routerLink="/login">Login</a>
  }
</mat-toolbar>
<main><router-outlet /></main>
```

### `LoginComponent` (route: `/login`)
- Centered `mat-card`, `MatInput` fields for username + password
- `loading = signal(false)`, `error = signal<string|null>(null)`
- On submit → `authService.login()` → redirect to `/submit` → on 401 set error signal
- `@if (error())` block below form

### `TicketSubmitComponent` (route: `/submit`, auth-guarded)
- Reactive form via `inject(FormBuilder).nonNullable.group({...})`
- Fields: `title` (min 3, max 200 + char counter), `description` (min 10, max 5000 + char counter), `priority` (MatSelect 1-5), `category` (optional MatSelect)
- `duplicateError = computed(() => error()?.error_code === 'DUPLICATE_TICKET' ? error() : null)`
- On 409 → show warning card with "View existing ticket" link using `err.error.detail.existing_ticket_id`
- On 202 → `router.navigate(['/tickets', response.ticket_id])`

### `TicketStatusComponent` (route: `/tickets/:id`)
- `@Input() id!: string` bound by router
- Signals: `ticket = signal<TicketDetailResponse|null>(null)`, `liveStatus = signal<TicketStatus|null>(null)`
- `currentStepIndex = computed(() => PIPELINE_STEPS.indexOf(liveStatus() ?? ticket()?.status ?? 'new'))`
- On init: fetch full ticket + subscribe WS (via `takeUntilDestroyed()`)
- On `done` WS event → re-fetch full ticket to hydrate classification + resolution

```html
@if (ticket()?.pii_detected) { <mat-card class="pii-banner">⚠ PII Detected & Masked</mat-card> }

<mat-stepper [selectedIndex]="currentStepIndex()" linear="false">
  @for (step of PIPELINE_STEPS; track step) {
    <mat-step [label]="step | titlecase" [completed]="isStepComplete(step)" />
  }
</mat-stepper>

@if (ticket()?.classification; as cls) { <app-classification-card [classification]="cls" /> }
@if (ticket()?.resolution; as res)     { <app-resolution-card [resolution]="res" /> }
@if (isAuthed() && ticket()?.resolution) { <app-feedback-panel [ticketId]="id" /> }
```

### `ClassificationCardComponent` (`@Input() classification`)
- Large confidence %, `mat-chip` colored by level (green/amber/red)
- `@if (classification.is_multi_domain)` → amber "Multi-Domain Issue" chip
- `@for (cat of classification.top_categories; track cat.category)` → `mat-progress-bar` per category

### `ResolutionCardComponent` (`@Input() resolution`)
- `@switch (resolution.routing_decision)` → green/blue/red chip
- `@if` blocks for: assigned department, escalation reason, is_repeated_issue warning
- `<app-star-rating [score]="resolution.llm_quality_score" [max]="5" />`
- Suggested steps in pre-formatted block; retrieved tickets list with similarity bars

### `FeedbackPanelComponent` (`@Input() ticketId`)
- `action = signal<FeedbackAction|null>(null)`, `submitted = signal(false)`
- Three `mat-button-toggle`: Accept / Modify / Reject
- `@if (action() === 'modified')` → required textarea for modified resolution
- On submit → `ticketService.submitFeedback()` → 204 → snackbar success message

### `DashboardComponent` (route: `/dashboard`)
- On init: `dashboardService.getRecentTickets()` → `tickets.set(response.items)`
- `kpis = computed(() => dashboardService.computeKpis(this.tickets()))`
- 4 `mat-card` KPI chips: Total | Auto-Resolve % | Escalation % | Avg Quality (N/A)
- `<app-category-chart [items]="tickets()" />`
- `mat-table` columns: title, category, status (StatusBadge), priority (PriorityChip), created_at; `mat-paginator`

### `CategoryChartComponent` (`@Input() items: TicketSummary[]`)
- Chart.js doughnut, tree-shaken: `Chart.register(ArcElement, DoughnutController, Legend, Tooltip)`
- `effect()` rebuilds chart data on items change: count tickets per category

---

## 8. Shared Components

| Component | Input | Behavior |
|---|---|---|
| `StatusBadgeComponent` | `status: TicketStatus` | `mat-chip` green/blue/red/amber/grey by status group |
| `PriorityChipComponent` | `priority: number` | `mat-chip` Critical/High/Medium/Low/Info |
| `StarRatingComponent` | `score: number\|null`, `max=5` | Filled/empty `mat-icon` stars |

Status color groups: green=auto_resolved, blue=assigned, red=escalated, amber=in-progress states, grey=closed/reopened

---

## 9. Key Dependencies

```json
{
  "@angular/animations": "^20.0.0",
  "@angular/cdk": "^20.0.0",
  "@angular/common": "^20.0.0",
  "@angular/core": "^20.0.0",
  "@angular/forms": "^20.0.0",
  "@angular/material": "^20.0.0",
  "@angular/platform-browser": "^20.0.0",
  "@angular/router": "^20.0.0",
  "chart.js": "^4.4.0",
  "rxjs": "^7.8.0",
  "zone.js": "^0.15.0"
}
```

Dev: `@angular/cli: ^20.0.0`, `typescript: ~5.8.0`

---

## 10. Dockerfile (Multi-Stage)

```dockerfile
# Stage 1: Build
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --prefer-offline
COPY . .
RUN npm run build -- --configuration=production

# Stage 2: Serve
FROM nginx:1.27-alpine AS runtime
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist/frontend/browser /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

Angular 20 CLI outputs to `dist/<project>/browser/` — verify `outputPath` in `angular.json`.

---

## 11. `nginx.conf`

```nginx
worker_processes auto;
events { worker_connections 1024; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    gzip on;
    gzip_types text/plain text/css application/javascript application/json;

    server {
        listen 80;
        root /usr/share/nginx/html;
        index index.html;

        # SPA fallback — Angular client-side routing
        location / { try_files $uri $uri/ /index.html; }

        # Proxy REST API → FastAPI backend (service name "api" in Docker network)
        location /api/ {
            proxy_pass http://api:8000;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # Proxy WebSocket → FastAPI backend
        location /ws/ {
            proxy_pass http://api:8000;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_read_timeout 3600s;
        }

        # Static asset long-term caching
        location ~* \.(js|css|png|ico|woff2?)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
}
```

---

## 12. Angular 20 Mandatory Patterns

| Rule | Correct | Wrong |
|---|---|---|
| DI | `inject(Service)` in class body | constructor injection |
| State | `signal()` / `computed()` | class fields + manual CD |
| Templates | `@if`, `@for`, `@switch` | `*ngIf`, `*ngFor`, `[ngSwitch]` |
| Cleanup | `takeUntilDestroyed()` | manual subscription + `ngOnDestroy` |
| HTTP setup | `provideHttpClient(withFetch())` | `HttpClientModule` |
| Animations | `provideAnimationsAsync()` | `BrowserAnimationsModule` |
| Route loading | `loadComponent: () => import(...)` | eager `component:` |

**Key gotchas:**
- Every standalone component must declare all Material modules in its own `imports: []`
- In Docker/prod, WS URL: `ws://${window.location.host}/ws/...` (nginx proxies; do not hardcode)
- 409 error: read `err.error.detail.existing_ticket_id` for the existing ticket link
- `mat-stepper` needs `linear="false"` since terminal statuses can be reached non-linearly
- `zone.js` is still required — zoneless is experimental in Angular 20

---

## 13. Implementation Sequence

1. Scaffold: `ng new frontend --standalone --routing --style=scss` inside `app_v2/`
2. `ng add @angular/material` → indigo/amber theme + typography
3. `npm install chart.js`
4. Create `src/environments/` files
5. Core layer: models → services → interceptor → guard
6. `app.config.ts` + `app.routes.ts` + `app.component`
7. Shared components (status-badge, priority-chip, star-rating, pipes)
8. `LoginComponent` → smoke-test auth flow
9. `TicketSubmitComponent` → smoke-test ingest + 409 handling
10. `TicketStatusComponent` + sub-cards → smoke-test WS + classification/resolution display
11. `DashboardComponent` → smoke-test list API + chart
12. `Dockerfile` + `nginx.conf`
13. `docker compose up --build` full-stack integration test

---

## 14. Verification

```bash
# Local dev (backend must be running on :8000)
cd app_v2/frontend
npm install && npm start
# → http://localhost:4200

# Docker build only
docker build -t ticketiq-frontend .
docker run -p 4200:80 ticketiq-frontend
# curl http://localhost:4200/api/v1/health/live → {"status":"ok"} (via nginx proxy)

# Full stack
cd app_v2/docker
docker compose up --build
```

**Smoke test checklist:**
- [ ] Login rejects bad credentials; accepts admin credentials; JWT appears in localStorage
- [ ] Authorization header sent on ingest request (DevTools Network tab)
- [ ] Ticket submit validates short title/description client-side before API call
- [ ] Valid submission navigates to `/tickets/{uuid}`, WS connects, stepper advances live
- [ ] Classification card appears after `done` WS event
- [ ] Resolution card shows suggested steps, quality stars, routing chip, department
- [ ] Authenticated user sees feedback panel; logged-out user does not
- [ ] Feedback Accept → 204 snackbar; Modify requires text; Reject dismisses
- [ ] Dashboard KPI cards show counts; category chart renders; table has status badges + priority chips
- [ ] Duplicate ticket → warning card with "View existing ticket" link
- [ ] PII warning banner shows when `pii_detected = true`
- [ ] Browser refresh on `/tickets/{id}` stays on page (nginx SPA fallback working)
- [ ] Logout clears token; `/submit` redirects to `/login`
