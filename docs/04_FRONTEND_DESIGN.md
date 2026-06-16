# Frontend Design (v2)

React 19 + Vite 6 + TypeScript (strict) + Tailwind CSS — kept from v1
(see [`01_LESSONS_LEARNED.md`](01_LESSONS_LEARNED.md)), but restructured from v1's
flat `components/` directory into the feature-based layout
[`CLAUDE.md`](../CLAUDE.md) §3 specifies, since v1 organized by technical role
(`components/`, `hooks/`, `api/`) rather than by feature.

## Project Structure

```
src/
  types.ts                 # shared API response/request types
  api/
    client.ts               # module-level singleton fetch wrapper (kept from v1 — proven good)
  features/
    auth/
      components/LoginForm.tsx
      hooks/useAuth.ts
      index.ts
    intake/
      components/IntakeTab.tsx
      hooks/useIngestTicket.ts
      index.ts
    resolution/
      components/ResolutionTab.tsx
      components/ReclassifyPanel.tsx   # NEW — human-in-the-loop reclassification UI
      hooks/useTickets.ts
      hooks/useWebSocket.ts
      index.ts
    kb/
      components/KBTab.tsx
      index.ts
    agent-sandbox/
      components/AgentTab.tsx
      index.ts
    analytics/
      components/AnalyticsTab.tsx
      index.ts
  shared/
    components/  ConfidenceBadge.tsx, DomainBadge.tsx, ClassificationPanel.tsx, RoutingPanel.tsx
    constants.ts  DOMAIN_STYLES, TERMINAL_STATUSES, STATUS_STEP_MAP, etc.
    utils.ts
  app/
    App.tsx
    routes.tsx
```

Each feature's `index.ts` is the only import surface other features may use,
per `CLAUDE.md` §3.

## Typed API Client — kept from v1

v1's `api/client.ts` (module-level singleton, `setClientToken`/
`setUnauthorizedHandler` decoupling auth from React state) worked well and is
carried forward unchanged in shape, with two additions:

```ts
export async function reclassifyTicket(ticketId: string, category: Category): Promise<void>;
export async function refreshAccessToken(): Promise<AuthTokenResponse>;
```

`refreshAccessToken()` is called transparently by a `401` interceptor before
falling back to full logout, now that the backend actually implements
`/auth/refresh` (see [`03_BACKEND_DESIGN.md` § Auth](03_BACKEND_DESIGN.md)).

## `types.ts` additions

```ts
export type TicketStatus =
  | "new" | "classifying" | "classified" | "awaiting_review"   // NEW
  | "retrieving" | "generating" | "evaluating"
  | "auto_resolved" | "assigned" | "escalated" | "closed" | "reopened";

export interface ResolutionStep {
  step_number: number;
  instruction: string;
}

export interface Resolution {
  ...
  suggested_steps: ResolutionStep[] | null;  // structured, not free text — no client-side parsing
}
```

Because the backend now returns structured steps (see
[`03_BACKEND_DESIGN.md` § Resolution Schema](03_BACKEND_DESIGN.md)), the v1
`splitSteps()` markdown-parsing utility (and the bug class it caused — UAT KB-05) is
deleted entirely; components render `resolution.suggested_steps.map(...)` directly.

## Reclassification Flow (new)

`ResolutionTab.tsx`, when `activeTicket.status === "awaiting_review"`:

- Renders `<ReclassifyPanel>` in place of the resolution-steps section: a `<select>`
  of the 6 `TicketCategory` values + submit button, plus the escalation reason
  (multi-domain or low-confidence, with the actual confidence score) pulled from
  `resolution.escalation_reason` — unchanged display logic from v1's `RoutingPanel`.
- Commit/Save/Reject feedback buttons are disabled in this status — there is no
  resolution yet to act on.
- On submit: `useTickets().reclassifyTicket(category)` calls the client, flips
  `isPolling = true` so the existing WebSocket/poll cycle picks up the resumed
  pipeline, shows a notice, and the queue badge updates automatically once the
  ticket transitions through `classifying → retrieving → ... → terminal`.

## Status Badge / Stepper Updates

`shared/constants.ts`:

```ts
export const TERMINAL_STATUSES = ["auto_resolved", "assigned", "escalated", "closed"] as const;
// awaiting_review is intentionally excluded — the pipeline resumes

export const STATUS_STEP_MAP: Record<string, number> = {
  new: 0, classifying: 1, classified: 1,
  awaiting_review: 1,      // parked right after Classify
  retrieving: 2, generating: 3, evaluating: 4, reopened: 0,
};

export const STATUS_COLORS: Record<string, string> = {
  auto_resolved: "emerald", assigned: "blue", escalated: "rose",
  awaiting_review: "amber",   // distinct from escalated — needs action, not a dead end
};
```

## Accessibility & Testing — baked in, not retrofitted

v1 added `htmlFor`/`id` pairing, `button` instead of `div onClick`, `role="alert"`,
and `aria-label`s as a late pass. v2 components are written with these from the
first commit, per `CLAUDE.md` §10. Every component ships with a co-located
`*.spec.tsx` using Testing Library, querying by role/accessible name — not CSS
class or test ID — per `CLAUDE.md` §13.

## What's unchanged from v1 (proven good, no reason to touch)

- `CoreParticleCanvas.tsx` Three.js background — purely decorative, no logic risk.
- WebSocket-driven live status updates (`useWebSocket.ts`) with the stale-closure
  ref pattern.
- Tailwind utility-first styling, mobile-first breakpoints.
- `AnimatePresence` tab transitions.
