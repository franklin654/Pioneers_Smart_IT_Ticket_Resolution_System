import { useState, useCallback } from "react";
import { DOMAIN_STYLES } from "../../../shared/constants";
import type { Category } from "../../../types";

interface KBEntry {
  id: string;
  title: string;
  content: string;
  category: Category;
  source_ticket_id: string | null;
  created_at: string;
}

interface KBResponse {
  data: KBEntry[];
  meta: { total: number; offset: number; limit: number };
}

export function KBTab() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [entries, setEntries] = useState<KBEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

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
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
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
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-4 space-y-1"
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-medium text-slate-100">{e.title}</h3>
                  <span
                    className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium bg-${style.color}-500/20 text-${style.color}-300`}
                  >
                    {style.label}
                  </span>
                </div>
                <p className="text-sm text-slate-400 line-clamp-3">{e.content}</p>
                {e.source_ticket_id && (
                  <p className="text-xs text-slate-600">
                    Source ticket:{" "}
                    <span className="font-mono">{e.source_ticket_id}</span>
                  </p>
                )}
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
    </div>
  );
}
