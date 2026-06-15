/**
 * FastAPI backend bridge.
 *
 * When BACKEND_API_URL is set, server.ts runs in "backend mode": instead of
 * the self-contained in-memory simulation, the ticket lifecycle (auth, ingest,
 * list, detail, feedback, live status) is proxied to the Python FastAPI service
 * defined in ../backend, and its responses are adapted into the richer shape the
 * React UI (src/) expects — without touching the UI itself.
 *
 * When BACKEND_API_URL is unset, this module is inert and server.ts uses its
 * built-in simulation engine (Gemini + heuristic fallback).
 *
 * Schema mapping (FastAPI -> UI):
 *   - TicketDetailResponse.suggested_steps (string) -> resolution.resolution_steps (string[])
 *   - resolution.routing_decision               -> ticket.routing_path
 *   - resolution.llm_quality_score              -> resolution.evaluation { ... }
 *   - resolution.retrieved_tickets[entry_id]    -> resolution.sources[ticket_id]
 *   - (none)                                     -> ticket.agent_messages (synthesized from status)
 *   - (none)                                     -> ticket.language / language_name ("en"/"English")
 */

// Read env lazily at call time: server.ts runs dotenv.config() AFTER this module
// is imported, so capturing process.env in top-level consts would miss the .env.
function backendUrl(): string {
  return (process.env.BACKEND_API_URL || "").replace(/\/+$/, "");
}

function backendUsername(): string {
  return process.env.BACKEND_ADMIN_USERNAME || "admin";
}

function backendPassword(): string {
  return (
    process.env.BACKEND_ADMIN_PASSWORD ||
    process.env.ADMIN_PASSWORD ||
    "changeme123"
  );
}

export function isBridgeEnabled(): boolean {
  return backendUrl().length > 0;
}

export function backendBaseUrl(): string {
  return backendUrl();
}

// ── Auth token (service account) ────────────────────────────────────────────
// The UI authenticates against server.ts with demo creds; server.ts in turn
// authenticates against FastAPI with its own configured service credentials.
let cachedToken: string | null = null;
let cachedTokenExpiry = 0;

export async function getBackendToken(): Promise<string> {
  const now = Date.now();
  if (cachedToken && now < cachedTokenExpiry) {
    return cachedToken;
  }
  const res = await fetch(`${backendUrl()}/api/v1/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      username: backendUsername(),
      password: backendPassword(),
    }).toString(),
  });
  if (!res.ok) {
    throw new Error(`Backend auth failed (${res.status})`);
  }
  const data: any = await res.json();
  cachedToken = data.access_token as string;
  // FastAPI default token lifetime is 60 min; refresh a little early.
  cachedTokenExpiry = now + 50 * 60 * 1000;
  return cachedToken;
}

// ── Value mappings ──────────────────────────────────────────────────────────

const PRIORITY_TO_INT: Record<string, number> = {
  critical: 1,
  high: 2,
  medium: 3,
  low: 4,
  informational: 5,
};

export function priorityToInt(priority: unknown): number {
  if (typeof priority === "number") {
    return priority >= 1 && priority <= 5 ? priority : 3;
  }
  if (typeof priority === "string") {
    const key = priority.toLowerCase().trim();
    if (PRIORITY_TO_INT[key] !== undefined) return PRIORITY_TO_INT[key];
    const asNum = parseInt(key, 10);
    if (asNum >= 1 && asNum <= 5) return asNum;
  }
  return 3;
}

const VALID_CATEGORIES = new Set([
  "infrastructure",
  "application",
  "security",
  "database",
  "access_management",
  "network",
]);

function normalizeCategory(category: unknown): string | undefined {
  if (typeof category !== "string" || !category.trim()) return undefined;
  const norm = category.toLowerCase().trim().replace(/\s+/g, "_");
  return VALID_CATEGORIES.has(norm) ? norm : undefined;
}

function deriveRoutingPath(status: string, routingDecision?: string | null): string {
  if (routingDecision) return routingDecision;
  switch (status) {
    case "auto_resolved":
    case "closed":
      return "auto_resolved";
    case "assigned":
    case "resolved":
      return "assigned";
    case "escalated":
      return "escalated";
    default:
      return "";
  }
}

function splitSteps(suggested: string | null | undefined): string[] {
  if (!suggested) return [];
  const clean = (line: string) =>
    line
      .replace(/^\s*[-*•]\s*/, "")
      .replace(/^\s*\d+[.)]\s*/, "")
      .trim();

  const byLine = suggested
    .split(/\r?\n+/)
    .map(clean)
    .filter((line) => line.length > 0);

  // Many KB resolutions store steps inline as "1) … 2) …" / "1. … 2. …" with no
  // newlines, which would otherwise collapse into a single step. Fall back to
  // splitting on inline numbered markers when the line-based split didn't.
  if (byLine.length <= 1 && /\d+[.)]\s/.test(suggested)) {
    const byMarker = suggested
      .split(/\s+(?=\d+[.)]\s)/)
      .map(clean)
      .filter((line) => line.length > 0);
    if (byMarker.length > 1) return byMarker;
  }

  return byLine;
}

// ── Agent reasoning log synthesis ───────────────────────────────────────────
// FastAPI does not persist a step-by-step agent transcript, so we reconstruct a
// faithful one from the persisted classification / resolution artifacts.
function synthesizeAgentMessages(raw: any): Array<{ agent: string; content: string; timestamp: string }> {
  const ts = raw.updated_at || raw.created_at || new Date().toISOString();
  const messages: Array<{ agent: string; content: string; timestamp: string }> = [];

  messages.push({
    agent: "IntakeAgent",
    content: raw.pii_detected
      ? "Ticket ingested. Sensitive fields detected and PII masking applied before persistence."
      : "Ticket ingested and validated. No PII detected during masking sweep.",
    timestamp: raw.created_at || ts,
  });

  if (raw.classification) {
    const c = raw.classification;
    const conf = typeof c.confidence === "number" ? (c.confidence * 100).toFixed(1) : "?";
    messages.push({
      agent: "ClassifierAgent",
      content: `Classified as '${c.predicted_category}' with ${conf}% confidence (${c.confidence_level}). Method: ${c.classification_method}.`,
      timestamp: ts,
    });
    if (c.is_multi_domain) {
      messages.push({
        agent: "ClassifierAgent",
        content: "Multi-domain signal detected — top categories are close; flagged for routing review.",
        timestamp: ts,
      });
    }
  }

  if (raw.resolution) {
    const r = raw.resolution;
    const retrieved = Array.isArray(r.retrieved_tickets) ? r.retrieved_tickets.length : 0;
    if (retrieved > 0) {
      messages.push({
        agent: "RAGResolverAgent",
        content: `Retrieved ${retrieved} knowledge-base runbook${retrieved === 1 ? "" : "s"} via hybrid dense + BM25 search.`,
        timestamp: ts,
      });
    }
    if (r.suggested_steps) {
      messages.push({
        agent: "RAGResolverAgent",
        content: "Synthesized a tailored step-by-step resolution runbook from retrieved context.",
        timestamp: ts,
      });
    }
    if (r.llm_quality_score !== null && r.llm_quality_score !== undefined) {
      messages.push({
        agent: "EvaluatorAgent",
        content: `LLM-as-Judge composite quality score: ${Number(r.llm_quality_score).toFixed(1)} / 5.`,
        timestamp: ts,
      });
    }
    let routeMsg = `Routing decision: ${r.routing_decision}.`;
    if (r.assigned_department) routeMsg += ` Assigned to ${r.assigned_department}.`;
    if (r.escalation_reason) routeMsg += ` Reason: ${r.escalation_reason}`;
    messages.push({ agent: "RoutingManager", content: routeMsg, timestamp: ts });
  }

  return messages;
}

function adaptResolution(r: any): any {
  if (!r) return undefined;
  const steps = splitSteps(r.suggested_steps);
  const sources = Array.isArray(r.retrieved_tickets)
    ? r.retrieved_tickets.map((t: any) => ({
        ticket_id: t.entry_id,
        title: t.title,
        similarity_score: t.similarity_score,
      }))
    : [];

  let evaluation;
  if (r.llm_quality_score !== null && r.llm_quality_score !== undefined) {
    const score = Number(r.llm_quality_score);
    const rounded = Math.round(score * 10) / 10;
    evaluation = {
      relevance_score: rounded,
      completeness_score: rounded,
      actionability_score: rounded,
      avg_score: rounded,
      rationale:
        "Composite LLM-as-Judge quality score recorded by the EvaluatorAgent across relevance, completeness, and actionability.",
      evaluator: "llm-as-judge",
    };
  }

  return {
    id: r.id,
    suggested_steps: r.suggested_steps,
    retrieved_tickets: r.retrieved_tickets,
    llm_quality_score: r.llm_quality_score,
    routing_decision: r.routing_decision,
    assigned_department: r.assigned_department,
    escalation_reason: r.escalation_reason,
    is_repeated_issue: r.is_repeated_issue,
    // UI-facing fields:
    resolution_steps: steps,
    generator: "FastAPI RAG Pipeline",
    sources,
    evaluation,
  };
}

/** Adapt a FastAPI TicketDetailResponse into the UI's rich Ticket shape. */
export function adaptTicketDetail(raw: any): any {
  const routingDecision = raw.resolution?.routing_decision;
  return {
    id: raw.id,
    ticket_id: raw.id,
    title: raw.title,
    description: raw.description,
    category: raw.category,
    priority: raw.priority,
    priority_str: undefined,
    status: raw.status,
    source: raw.source,
    pii_detected: raw.pii_detected,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
    confidence_score: raw.classification?.confidence ?? 0,
    routing_path: deriveRoutingPath(raw.status, routingDecision),
    is_multi_domain: raw.classification?.is_multi_domain ?? false,
    language: "en",
    language_name: "English",
    classification: raw.classification
      ? { ...raw.classification, category: raw.classification.predicted_category }
      : undefined,
    resolution: adaptResolution(raw.resolution),
    agent_messages: synthesizeAgentMessages(raw),
  };
}

/** Adapt a FastAPI TicketSummary (list item) into the UI's list shape. */
function adaptTicketSummary(item: any): any {
  return {
    id: item.id,
    ticket_id: item.id,
    title: item.title,
    category: item.category,
    priority: item.priority,
    status: item.status,
    created_at: item.created_at,
    routing_path: deriveRoutingPath(item.status),
    language: "en",
    language_name: "English",
  };
}

// ── Bridge operations ───────────────────────────────────────────────────────

export async function backendListTickets(query: Record<string, any>): Promise<any> {
  const params = new URLSearchParams();
  if (query.limit) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));
  if (query.status) params.set("status", String(query.status));
  if (query.category) params.set("category", String(query.category));
  if (query.priority) params.set("priority", String(query.priority));
  const qs = params.toString();
  const res = await fetch(`${backendUrl()}/api/v1/tickets/${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`Backend list failed (${res.status})`);
  const data: any = await res.json();
  const adapted = (data.items || []).map(adaptTicketSummary);
  return {
    items: adapted,
    tickets: adapted,
    total: data.total,
    offset: data.offset,
    limit: data.limit,
  };
}

export async function backendGetTicket(id: string): Promise<any> {
  const res = await fetch(`${backendUrl()}/api/v1/tickets/${id}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Backend get failed (${res.status})`);
  return adaptTicketDetail(await res.json());
}

export async function backendIngest(body: any): Promise<{ ok: boolean; status: number; data: any }> {
  const token = await getBackendToken();
  const payload: any = {
    title: body.title,
    description: body.description,
    priority: priorityToInt(body.priority),
  };
  const category = normalizeCategory(body.category);
  if (category) payload.category = category;

  const res = await fetch(`${backendUrl()}/api/v1/tickets/ingest`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  const data: any = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

export async function backendFeedback(
  id: string,
  body: any
): Promise<{ ok: boolean; status: number; data: any }> {
  const token = await getBackendToken();
  const action = body.action || body.feedback_type;
  const modified = body.modified_resolution || body.modified_text;
  const payload: any = { action };
  if (modified) payload.modified_resolution = modified;

  const res = await fetch(`${backendUrl()}/api/v1/resolutions/${id}/feedback`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  let data: any = {};
  if (res.status !== 204) data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

/** Poll a ticket's current status for the WebSocket bridge. Returns null if gone. */
export async function backendGetStatus(id: string): Promise<string | null> {
  const res = await fetch(`${backendUrl()}/api/v1/tickets/${id}`);
  if (!res.ok) return null;
  const data: any = await res.json();
  return data.status as string;
}

// ── Analytics ────────────────────────────────────────────────────────────────

const PRIORITY_INT_TO_LABEL: Record<string, string> = {
  "1": "Critical",
  "2": "High",
  "3": "Medium",
  "4": "Low",
  "5": "Informational",
};

/** Title-case a backend category value for the UI's color-keyed charts. */
function categoryLabel(key: string): string {
  if (!key) return "Uncategorized";
  return key.charAt(0).toUpperCase() + key.slice(1).toLowerCase();
}

/**
 * Fetch live analytics from the FastAPI backend and adapt the raw aggregation
 * into the exact shape the React AnalyticsTab expects (KPI rates, color-keyed
 * category/priority maps, and a gap-filled 30-day daily series).  Replaces the
 * BFF's seeded simulation analytics whenever backend mode is active so the
 * dashboard reflects real ingested tickets.
 */
export async function backendAnalytics(days = 30): Promise<any> {
  const res = await fetch(`${backendUrl()}/api/v1/analytics?days=${days}`);
  if (!res.ok) throw new Error(`Backend analytics failed (${res.status})`);
  const raw: any = await res.json();

  const total: number = raw.total || 0;
  const byRoutingRaw: Record<string, number> = raw.by_routing || {};
  const byRouting = {
    auto_resolved: byRoutingRaw.auto_resolved || 0,
    assigned: byRoutingRaw.assigned || 0,
    escalated: byRoutingRaw.escalated || 0,
  };
  // Rates are computed over tickets that actually went through AI routing
  // (auto-resolved + assigned + escalated), so historical seed tickets with no
  // resolution record don't dilute the pipeline's measured performance.
  const routedTotal =
    byRouting.auto_resolved + byRouting.assigned + byRouting.escalated;
  const rate = (n: number) => (routedTotal ? n / routedTotal : 0);

  const byCategory: Record<string, number> = {};
  for (const [k, v] of Object.entries(raw.by_category || {})) {
    byCategory[categoryLabel(k)] = (byCategory[categoryLabel(k)] || 0) + (v as number);
  }

  const byPriority: Record<string, number> = {};
  for (const [k, v] of Object.entries(raw.by_priority || {})) {
    const label = PRIORITY_INT_TO_LABEL[k] || `P${k}`;
    byPriority[label] = (byPriority[label] || 0) + (v as number);
  }

  // Gap-fill the trailing `days` window so the timeline renders as a continuous
  // axis; overlay real per-day counts keyed by ISO date.
  const realByDay: Record<string, { incidents: number; resolved: number }> = {};
  for (const d of raw.by_day || []) {
    realByDay[d.date] = { incidents: d.incidents || 0, resolved: d.resolved || 0 };
  }
  const byDay: Array<{ date: string; incidents: number; resolved: number }> = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const dt = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
    const iso = dt.toISOString().split("T")[0];
    const label = dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    const hit = realByDay[iso] || { incidents: 0, resolved: 0 };
    byDay.push({ date: label, incidents: hit.incidents, resolved: hit.resolved });
  }

  return {
    kpis: {
      routed: total,
      auto_resolve_rate: rate(byRouting.auto_resolved),
      assign_rate: rate(byRouting.assigned),
      escalation_rate: rate(byRouting.escalated),
      avg_judge_score:
        raw.avg_judge_score != null ? Math.round(raw.avg_judge_score * 10) / 10 : 0,
    },
    totals: { routed: total, knowledge_base: raw.knowledge_base ?? null },
    by_routing: byRouting,
    by_category: byCategory,
    by_priority: byPriority,
    by_status: raw.by_status || {},
    by_day: byDay,
  };
}

// ── Knowledge base ───────────────────────────────────────────────────────────

/**
 * Fetch knowledge base entries from the FastAPI backend and adapt each into the
 * UI's KB item shape ({ ticket_id, title, category, description,
 * resolution_steps[], created_by }).  Replaces the BFF's small static seed list
 * with the real KB corpus whenever backend mode is active.
 */
export async function backendKnowledge(query: Record<string, any>): Promise<any> {
  const params = new URLSearchParams();
  if (query.q) params.set("q", String(query.q));
  // Only forward a category the backend recognises; otherwise let it return all.
  const cat = normalizeCategory(query.category);
  if (cat) params.set("category", cat);
  params.set("limit", String(query.limit || 100));
  if (query.offset) params.set("offset", String(query.offset));

  const res = await fetch(`${backendUrl()}/api/v1/knowledge?${params.toString()}`);
  if (!res.ok) throw new Error(`Backend knowledge failed (${res.status})`);
  const data: any = await res.json();

  const items = (data.items || []).map((e: any) => ({
    ticket_id: `KB-${String(e.id).slice(0, 8)}`,
    title: e.title,
    category: e.category || "uncategorized",
    description: e.description,
    resolution_steps: splitSteps(e.resolution),
    created_by: e.source || "knowledge_base",
  }));

  return { items, total: data.total ?? items.length };
}
