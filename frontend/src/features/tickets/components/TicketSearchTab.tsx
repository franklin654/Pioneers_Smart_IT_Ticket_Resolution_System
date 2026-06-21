import { useState, useCallback } from "react";
import {
  DOMAIN_STYLES,
  STATUS_LABELS,
  STATUS_COLORS,
  CATEGORIES,
} from "../../../shared/constants";
import { formatDate, priorityLabel, priorityColor } from "../../../shared/utils";
import type { Category, Ticket, TicketStatus } from "../../../types";

const PAGE_SIZE = 20;

const ALL_STATUSES: TicketStatus[] = [
  "new", "classifying", "classified", "awaiting_review",
  "retrieving", "generating", "evaluating",
  "auto_resolved", "assigned", "escalated", "closed", "reopened",
];

interface Props {
  onOpenTicket: (id: string) => void;
}

export function TicketSearchTab({ onOpenTicket }: Props) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<TicketStatus | "">("");
  const [category, setCategory] = useState<Category | "">("");
  const [priority, setPriority] = useState<"" | "1" | "2" | "3">("");

  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const search = useCallback(async (newOffset = 0) => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (q.trim()) qs.set("q", q.trim());
      if (status) qs.set("status", status);
      if (category) qs.set("category", category);
      if (priority) qs.set("priority", priority);
      qs.set("offset", String(newOffset));
      qs.set("limit", String(PAGE_SIZE));

      const res = await fetch(`/api/v1/tickets/?${qs}`, {
        headers: { Authorization: `Bearer ${sessionStorage.getItem("token") ?? ""}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as {
        data: Ticket[];
        meta: { total: number; offset: number; limit: number };
      };
      setTickets(json.data);
      setTotal(json.meta.total);
      setOffset(newOffset);
      setSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }, [q, status, category, priority]);

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Ticket Search</h2>

      {/* Filters */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-4 space-y-3">
        {/* Keyword row */}
        <div className="flex gap-2">
          <input
            type="search"
            aria-label="Search tickets"
            placeholder="Search by title or description…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void search(0)}
            className="flex-1 rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          />
          <button
            onClick={() => void search(0)}
            disabled={loading}
            className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {loading ? "Searching…" : "Search"}
          </button>
        </div>

        {/* Filter row */}
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="Filter by status"
            value={status}
            onChange={(e) => setStatus(e.target.value as TicketStatus | "")}
            className="rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            <option value="">All statuses</option>
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>{STATUS_LABELS[s]}</option>
            ))}
          </select>

          <select
            aria-label="Filter by category"
            value={category}
            onChange={(e) => setCategory(e.target.value as Category | "")}
            className="rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            <option value="">All categories</option>
            {CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>{DOMAIN_STYLES[cat].label}</option>
            ))}
          </select>

          <select
            aria-label="Filter by priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as "" | "1" | "2" | "3")}
            className="rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            <option value="">All priorities</option>
            <option value="1">High</option>
            <option value="2">Medium</option>
            <option value="3">Low</option>
          </select>

          {(q || status || category || priority) && (
            <button
              onClick={() => {
                setQ(""); setStatus(""); setCategory(""); setPriority("");
                setSearched(false); setTickets([]); setTotal(0);
              }}
              className="text-xs text-slate-500 hover:text-slate-300 focus:outline-none focus:underline"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {error && <p role="alert" className="text-sm text-rose-400">{error}</p>}

      {searched && (
        <p className="text-xs text-slate-500" aria-live="polite">
          {total} {total === 1 ? "ticket" : "tickets"} found
        </p>
      )}

      {/* Results table */}
      {tickets.length > 0 && (
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-xs uppercase tracking-widest text-slate-500">
                <th className="px-4 py-3 text-left font-medium">Title</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Category</th>
                <th className="px-4 py-3 text-left font-medium">Priority</th>
                <th className="px-4 py-3 text-left font-medium">Created</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {tickets.map((t, i) => {
                const cat = t.classification?.predicted_category as Category | undefined;
                const catStyle = cat ? DOMAIN_STYLES[cat] : null;
                const statusColor = STATUS_COLORS[t.status] ?? "slate";
                return (
                  <tr
                    key={t.id}
                    className={`border-b border-[var(--color-border)] last:border-0 transition-colors hover:bg-slate-700/30 ${
                      i % 2 === 0 ? "" : "bg-slate-800/20"
                    }`}
                  >
                    <td className="px-4 py-3 text-slate-200 max-w-xs">
                      <span className="line-clamp-2">{t.title}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded px-2 py-0.5 text-xs font-medium bg-${statusColor}-500/20 text-${statusColor}-300`}>
                        {STATUS_LABELS[t.status]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {catStyle ? (
                        <span className={`rounded px-2 py-0.5 text-xs font-medium bg-${catStyle.color}-500/20 text-${catStyle.color}-300`}>
                          {catStyle.label}
                        </span>
                      ) : (
                        <span className="text-slate-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-medium text-${priorityColor(t.priority)}-400`}>
                        {priorityLabel(t.priority)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                      {formatDate(t.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => onOpenTicket(t.id)}
                        className="rounded-lg border border-indigo-600/50 px-3 py-1 text-xs font-medium text-indigo-400 hover:bg-indigo-600/20 hover:text-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      >
                        Open →
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-[var(--color-border)] px-4 py-3">
              <span className="text-xs text-slate-500">
                Page {currentPage} of {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => void search(offset - PAGE_SIZE)}
                  disabled={offset === 0 || loading}
                  className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  ← Prev
                </button>
                <button
                  onClick={() => void search(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= total || loading}
                  className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  Next →
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {searched && tickets.length === 0 && !loading && (
        <p className="text-sm text-slate-500">No tickets match your search.</p>
      )}

      {!searched && !loading && (
        <p className="text-sm text-slate-500">
          Use the filters above to search tickets. Leave all fields blank and click Search to browse all tickets.
        </p>
      )}
    </div>
  );
}
