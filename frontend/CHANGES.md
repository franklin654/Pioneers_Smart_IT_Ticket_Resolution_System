# TicketIQ Frontend — Implementation Report

## Overview

This document describes the migration from a simulation-based frontend (Express BFF + `backendBridge.ts`) to a
production-ready frontend that calls the real FastAPI backend endpoints. No backend Python files were modified.

---

## Architecture Change

### Before

```
Browser → Vite dev server (port 5173) → Express BFF (server.ts, port 3001)
                                         ├── Simulation engine (fake tickets, fake resolutions)
                                         ├── Fake WebSocket server
                                         ├── /api/v1/analytics (invented)
                                         ├── /api/v1/knowledge (invented)
                                         └── Google Gemini (translation)
```

### After

```
Browser → Vite dev server (port 5173) → [Vite proxy] → FastAPI backend (port 8000)
                                         ├── /api/* proxied to http://localhost:8000
                                         └── /ws/*  proxied to ws://localhost:8000
```

In production, `dist/` is served by a minimal `server.ts` (~30 lines) — no simulation routes, no JWT, no Gemini.

---

## Files Deleted

| File | Reason |
|---|---|
| `frontend/backendBridge.ts` | Entire simulation/BFF bridge — replaced by direct fetch calls with Vite proxy |
| `frontend/src/types.ts` | Contained simulation-specific types no longer needed |
| `frontend/src/components/WeatherCanvas.tsx` | Unused ambient component, dead code |

---

## Files Created

| File | Purpose |
|---|---|
| `frontend/src/components/LoginForm.tsx` | Full-screen login overlay; POSTs to `/api/v1/auth/token` (form-urlencoded); saves JWT to `sessionStorage` |

---

## Files Rewritten / Updated

### `frontend/vite.config.ts`
Added `server.proxy` to forward `/api` and `/ws` requests to FastAPI at `localhost:8000`. This replaces the Express BFF entirely in development.

### `frontend/server.ts`
Reduced from 1,496 lines to ~20 lines. Now only serves the `dist/` static build for production — no simulation logic.

### `frontend/package.json`
Changed `"dev"` script from `"tsx server.ts"` to `"vite"` — Vite handles dev serving now.

### `frontend/.env.example`
Simplified to a single `BACKEND_URL=http://localhost:8000` (Vite proxy uses this target).

### `frontend/src/index.css`
Added three mid-scale color tokens to the `@theme` block:
```css
--color-slate-550: oklch(0.52 0.01 248);
--color-slate-650: oklch(0.44 0.01 248);
--color-slate-850: oklch(0.20 0.01 248);
```
**Rule:** Any Tailwind utility class that uses a non-standard color step (not in the default 50–950 scale) MUST be defined here. Never write `text-slate-550` without a corresponding `@theme` token.

### `frontend/src/App.tsx`
Complete rewrite. Key changes:
- Auth: `LoginForm` overlay when no token; `sessionStorage` persistence; logout clears state
- `PRIORITY_MAP`: `{ critical:1, high:2, medium:3, low:4, informational:5 }` — maps form strings to backend ints
- `fetchTickets()`: uses `data.items || []`; ticket identity via `ticket.id` everywhere
- `handleTicketIngestion`: sends `{ title, description, priority: int, category? }` — no `source`, no `min_confidence_threshold`
- Analytics: computed client-side via `useMemo` from `ticketsList` (no backend analytics endpoint)
- `fetchResolvedCases()`: `GET /api/v1/tickets?status=auto_resolved&limit=50` — feeds the Resolved Cases tab
- WebSocket: connects to `/ws/tickets/${activeTicketId}`; on `status_changed`/`done` → refetches ticket via REST; on `done` → closes WS + refetches list
- Feedback: sends only `{ action, modified_resolution? }` — no extra fields
- Tab IDs: `"faq"` → `"cases"` (label: "Resolved Cases Reference")
- Footer: live stats bar (Total / Auto-Resolved / Assigned / Escalated counts)

### `frontend/src/components/IntakeTab.tsx`
- Removed `minConfidenceThreshold` / `setMinConfidenceThreshold` props and slider UI (backend ignores this field)
- Lowercase preset `cat` values: `"Database"` → `"database"`, `"Security"` → `"security"`, `"Infrastructure"` → `"infrastructure"`
- Priority options updated to `"Low (P4)"` … `"Critical (P1)"` format
- Added `exit={{ opacity: 0, y: -10 }}` motion prop

### `frontend/src/components/ResolutionTab.tsx`
- Uses `ticket.id` (not `ticket.ticket_id`) throughout
- `suggested_steps` split: `text.split("\n").map(s => s.replace(/^[\d]+\.\s*|^[-•*]\s*/, "").trim()).filter(Boolean)`
- Classification scorecard uses real backend fields: `predicted_category`, `confidence`, `confidence_level`, `top_categories`, `is_multi_domain`, `classification_method`
- Routing section shows: `routing_decision`, `assigned_department`, `escalation_reason`, `llm_quality_score`, `is_repeated_issue`
- Removed all translate props and UI (feature removed)
- Fixed `border-cyan-405` → `border-cyan-400`
- Added `exit={{ opacity: 0, y: -10 }}` motion prop

### `frontend/src/components/AgentTab.tsx`
- Removed fake terminal console (was rendering synthetic `agent_messages` from the BFF)
- Removed props: `revealCount`, `terminalBottomRef`
- Right panel replaced with three real data panels:
  1. **Processing Timeline** — ordered status steps with done/active/pending state
  2. **Classification Analysis** — `predicted_category`, `confidence`, `top_categories` bar chart, `confidence_level` badge
  3. **Resolution Details** — `routing_decision`, `llm_quality_score`, `assigned_department`, `escalation_reason`, `retrieved_tickets`
- Kept CoreParticleCanvas (left panel unchanged)
- Fixed `border-slate-850` → `border-slate-800`, `text-slate-650` → `text-slate-600`
- Added `exit={{ opacity: 0, y: -10 }}` motion prop

### `frontend/src/components/KBTab.tsx`
Complete rewrite as "Resolved Cases Reference" tab.
- **Old**: Required a non-existent `/api/v1/knowledge` endpoint; rendered simulated `KBItem[]`
- **New**: Props: `{ cases: any[], loading: boolean, onRefresh: () => void }` — data from `GET /api/v1/tickets?status=auto_resolved`
- Client-side search/filter by title and category
- Renders `resolution.suggested_steps` (split by newline), `resolution.retrieved_tickets` (KB sources), classification data
- Added `exit={{ opacity: 0, y: -10 }}` motion prop

### `frontend/src/components/AnalyticsTab.tsx`
- **Old**: Required a non-existent `/api/v1/analytics` endpoint; rendered `analyticsData.by_day` AreaChart
- **New**: Prop changed from `analyticsData` to `analytics: { total, by_routing, by_category }` (computed in App.tsx)
- Removed `AreaChart` / 30-day timeline (no daily history without analytics endpoint)
- Kept KPI cards (total, auto-resolve %, assigned %, escalation %) and BarChart for category breakdown
- Added routing breakdown (horizontal bar chart)
- Fixed `text-slate-550` → `text-slate-500`
- Added `exit={{ opacity: 0, y: -10 }}` motion prop

---

## Missing Endpoints & UI Replacements

| Backend Gap | Old UI | Replacement |
|---|---|---|
| No `/api/v1/analytics` | Fetched fake `kpis`, `by_day`, `by_priority` | Client-side `useMemo` from `ticketsList` — counts by routing/category |
| No `/api/v1/knowledge` | Rendered synthetic KB runbooks | Resolved Cases tab — real auto-resolved tickets from `GET /api/v1/tickets?status=auto_resolved` |
| No translate endpoint | "Translate" button in ResolutionTab | Feature removed entirely |
| No agent reasoning log | Fake `agent_messages[]` in AgentTab terminal | Real classification + resolution structured data panels |
| No `/api/v1/config`, `/api/v1/system` | Header system info badges | Removed |

---

## WebSocket Integration

**Endpoint:** `ws://localhost:8000/ws/tickets/{ticket_id}` (proxied via Vite as `/ws/tickets/{id}`)

**Message format from backend:**
```json
{ "event": "status_changed", "status": "classifying" }
{ "event": "done", "status": "auto_resolved" }
{ "event": "error", "message": "..." }
```

**Handling pattern:**
- Backend sends only `event` + `status` — NOT the full ticket object
- On `status_changed` or `done`: refetch full ticket via `GET /api/v1/tickets/{id}`
- On `done`: close WS, set `isPolling=false`, refetch ticket list
- On `error`: show notice, close WS

The old REST polling fallback (`setInterval`) has been removed — the backend WS is authoritative.

---

## Auth Flow

1. App starts → reads `ticketiq_token` from `sessionStorage`
2. If no token → show `LoginForm` (full-screen overlay)
3. Login: POST `/api/v1/auth/token` with `application/x-www-form-urlencoded`
4. On success: store `access_token` in `sessionStorage`, pass to App state
5. Protected calls: `Authorization: Bearer <token>` header on ingest and feedback
6. 401 response → call `handleLogout()` → clears token → shows login again

---

## Ticket Field Notes

- `TicketSummary.id` and `TicketDetailResponse.id` — always `id` (UUID string)
- `TicketIngestResponse` uses `ticket_id` (exception, only on the 202 response from ingest)
- `resolution.suggested_steps` is a **plain string** (newline-separated), not an array — split for display
- `classification` and `resolution` are `null` while processing; components guard for this

---

## Styling Rules

- All custom color tokens live in `@theme` in `frontend/src/index.css`
- Standard Tailwind scale (50, 100, 200 … 900, 950) is always available
- Mid-scale steps `slate-550`, `slate-650`, `slate-850` are defined in `@theme`
- **Never use** class names like `text-slate-405`, `border-cyan-450` without a matching `@theme` token
- No per-component style overrides — all tokens flow from a single `@theme` block

---

## Known Limitations

- **No historical daily chart**: The analytics tab shows live counts only. A `by_day` timeline would require a dedicated backend analytics endpoint.
- **No full-text KB search**: The resolved cases tab filters client-side. A vector search endpoint would be needed for semantic search.
- **No real-time ticket list updates**: The list refreshes on WebSocket `done` events and manual refresh. Continuous polling was intentionally removed.

---

## How to Run

### Development
```bash
cd frontend
npm install
npm run dev          # Vite at :5173, proxies /api and /ws to :8000
```
FastAPI backend must be running at `localhost:8000`.

### Production Build
```bash
cd frontend
npm run build        # outputs to dist/
npm run preview      # or: node server.ts (serves dist/)
```

### Default Credentials
Defined in the FastAPI backend (check `backend/app/core/config.py` or the backend README).
The frontend has no hardcoded credentials.
