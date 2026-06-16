import type {
  ApiResponse,
  AuthTokenResponse,
  Category,
  IngestRequest,
  IngestResponse,
  Meta,
  Ticket,
} from "../types";

const BASE = "/api/v1";

let _token: string | null = null;
let _onUnauthorized: (() => void) | null = null;

export function setClientToken(token: string | null): void {
  _token = token;
}

export function setUnauthorizedHandler(fn: () => void): void {
  _onUnauthorized = fn;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (_token) headers["Authorization"] = `Bearer ${_token}`;

  const res = await fetch(`${BASE}${path}`, { ...init, headers });

  if (res.status === 401) {
    // Try to refresh before falling back to logout
    const refreshed = await refreshAccessToken().catch(() => null);
    if (refreshed) {
      setClientToken(refreshed.access_token);
      headers["Authorization"] = `Bearer ${refreshed.access_token}`;
      const retry = await fetch(`${BASE}${path}`, { ...init, headers });
      if (retry.ok) return retry.json() as Promise<ApiResponse<T>>;
    }
    _onUnauthorized?.();
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      (body as { error?: { message?: string } }).error?.message ??
        `HTTP ${res.status}`,
    );
  }

  if (res.status === 204) return { data: undefined as unknown as T };
  return res.json() as Promise<ApiResponse<T>>;
}

// --- Auth ---

export async function login(
  username: string,
  password: string,
): Promise<AuthTokenResponse> {
  const body = new URLSearchParams({ username, password });
  const res = await fetch(`${BASE}/auth/token`, {
    method: "POST",
    body,
  });
  if (!res.ok) throw new Error("Invalid credentials.");
  const json = (await res.json()) as ApiResponse<AuthTokenResponse>;
  return json.data;
}

export async function refreshAccessToken(): Promise<AuthTokenResponse> {
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw new Error("Refresh failed.");
  const json = (await res.json()) as ApiResponse<AuthTokenResponse>;
  return json.data;
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, {
    method: "POST",
    headers: _token ? { Authorization: `Bearer ${_token}` } : {},
  });
  setClientToken(null);
}

// --- Tickets ---

export async function ingestTicket(
  req: IngestRequest,
): Promise<IngestResponse> {
  const r = await request<IngestResponse>("/tickets/ingest", {
    method: "POST",
    body: JSON.stringify(req),
  });
  return r.data;
}

export async function getTicket(id: string): Promise<Ticket> {
  const r = await request<Ticket>(`/tickets/${id}`);
  return r.data;
}

export async function listTickets(params?: {
  status?: string;
  category?: string;
  priority?: number;
  offset?: number;
  limit?: number;
}): Promise<{ tickets: Ticket[]; meta: Meta }> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.category) qs.set("category", params.category);
  if (params?.priority != null) qs.set("priority", String(params.priority));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const r = await request<Ticket[]>(`/tickets/${qs.size ? `?${qs}` : ""}`);
  return { tickets: r.data, meta: r.meta! };
}

export async function reclassifyTicket(
  ticketId: string,
  category: Category,
): Promise<void> {
  await request(`/tickets/${ticketId}/reclassify`, {
    method: "PATCH",
    body: JSON.stringify({ category }),
  });
}

// --- Resolutions ---

export async function submitFeedback(
  ticketId: string,
  action: "accepted" | "modified" | "rejected",
  modifiedResolution?: Array<{ step_number: number; instruction: string }>,
): Promise<void> {
  await request(`/resolutions/${ticketId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ action, modified_resolution: modifiedResolution }),
  });
}
