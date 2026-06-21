import { useState, useCallback, useEffect } from "react";
import { DOMAIN_STYLES } from "../../../shared/constants";
import { formatDate } from "../../../shared/utils";
import type { Category } from "../../../types";

interface KBEntry {
  id: string;
  title: string;
  content: string;
  category: Category;
  source_ticket_id: string | null;
  created_at: string;
  relevance_score?: number;
}

interface KBResponse {
  data: KBEntry[];
  meta: { total: number; offset: number; limit: number };
}

function KBEntryModal({ entry, onClose }: { entry: KBEntry; onClose: () => void }) {
  const style = DOMAIN_STYLES[entry.category];

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={entry.title}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-panel)] p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-base font-semibold text-slate-100 leading-snug">
            {entry.title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-700 hover:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            ✕
          </button>
        </div>

        {/* Meta */}
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
          <span
            className={`rounded px-2 py-0.5 font-medium bg-${style.color}-500/20 text-${style.color}-300`}
          >
            {style.label}
          </span>
          {entry.relevance_score !== undefined && (
            <span>{Math.round(entry.relevance_score * 100)}% semantic match</span>
          )}
          <span>{formatDate(entry.created_at)}</span>
          {entry.source_ticket_id && (
            <span>
              Source:{" "}
              <span className="font-mono text-slate-400">{entry.source_ticket_id}</span>
            </span>
          )}
        </div>

        <hr className="border-[var(--color-border)]" />

        {/* Full resolution content */}
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Resolution
          </p>
          <p className="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">
            {entry.content}
          </p>
        </div>
      </div>
    </div>
  );
}

export function KBTab() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [entries, setEntries] = useState<KBEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [selected, setSelected] = useState<KBEntry | null>(null);

  const search = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (query.trim()) qs.set("q", query.trim());
      if (category) qs.set("category", category);
      qs.set("limit", "20");
      const res = await fetch(`/api/v1/kb/?${qs}`, {
        headers: { Authorization: `Bearer ${sessionStorage.getItem("token") ?? ""}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as KBResponse;
      setEntries(json.data);
      setTotal(json.meta.total);
      setSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }, [query, category]);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Knowledge Base</h2>

      {/* Search bar */}
      <div className="flex gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-4">
        <input
          type="search"
          aria-label="Search knowledge base"
          placeholder="Search entries…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void search()}
          className="flex-1 rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
        />
        <select
          aria-label="Filter by category"
          value={category}
          onChange={(e) => setCategory(e.target.value as Category | "")}
          className="rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">All categories</option>
          {(Object.keys(DOMAIN_STYLES) as Category[]).map((cat) => (
            <option key={cat} value={cat}>
              {DOMAIN_STYLES[cat].label}
            </option>
          ))}
        </select>
        <button
          onClick={() => void search()}
          disabled={loading}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-rose-400">{error}</p>
      )}

      {searched && (
        <p className="text-xs text-slate-500" aria-live="polite">
          {total} {total === 1 ? "entry" : "entries"} found
        </p>
      )}

      {entries.length > 0 && (
        <ul role="list" className="space-y-3">
          {entries.map((e) => {
            const style = DOMAIN_STYLES[e.category];
            return (
              <li
                key={e.id}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-4 space-y-2"
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-medium text-slate-100">{e.title}</h3>
                  <div className="flex shrink-0 items-center gap-2">
                    {e.relevance_score !== undefined && (
                      <span className="text-xs text-slate-500">
                        {Math.round(e.relevance_score * 100)}% match
                      </span>
                    )}
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium bg-${style.color}-500/20 text-${style.color}-300`}
                    >
                      {style.label}
                    </span>
                  </div>
                </div>

                <p className="text-sm text-slate-400 line-clamp-3">{e.content}</p>

                <div className="flex items-center justify-between">
                  {e.source_ticket_id ? (
                    <p className="text-xs text-slate-600">
                      Source: <span className="font-mono">{e.source_ticket_id}</span>
                    </p>
                  ) : (
                    <span />
                  )}
                  <button
                    onClick={() => setSelected(e)}
                    className="text-xs font-medium text-indigo-400 hover:text-indigo-300 focus:outline-none focus:underline"
                  >
                    View full entry →
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {searched && entries.length === 0 && !loading && (
        <p className="text-sm text-slate-500">No entries match your search.</p>
      )}

      {!searched && !loading && (
        <p className="text-sm text-slate-500">
          Enter a search term or filter by category to browse knowledge base entries.
          Entries are automatically created from resolved tickets.
        </p>
      )}

      {selected && (
        <KBEntryModal entry={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
