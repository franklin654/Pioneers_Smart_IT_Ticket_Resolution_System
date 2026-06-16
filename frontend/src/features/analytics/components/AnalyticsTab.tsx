import { useEffect, useState } from "react";
import { listTickets } from "../../../api/client";
import { CATEGORIES, DOMAIN_STYLES, STATUS_LABELS } from "../../../shared/constants";
import type { Category, TicketStatus } from "../../../types";

interface StatusCount {
  status: TicketStatus;
  count: number;
}

interface CategoryCount {
  category: Category;
  count: number;
}

const TRACKED_STATUSES: TicketStatus[] = [
  "new",
  "classifying",
  "awaiting_review",
  "generating",
  "auto_resolved",
  "assigned",
  "escalated",
  "closed",
];

export function AnalyticsTab() {
  const [statusCounts, setStatusCounts] = useState<StatusCount[]>([]);
  const [categoryCounts, setCategoryCounts] = useState<CategoryCount[]>([]);
  const [totalTickets, setTotalTickets] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      setLoading(true);
      setError(null);
      try {
        const [allRes, ...statusRes] = await Promise.all([
          listTickets({ limit: 1 }),
          ...TRACKED_STATUSES.map((s) => listTickets({ status: s, limit: 1 })),
        ]);

        if (cancelled) return;

        setTotalTickets(allRes.meta.total);
        setStatusCounts(
          TRACKED_STATUSES.map((status, i) => ({
            status,
            count: statusRes[i]?.meta.total ?? 0,
          })),
        );

        const catResults = await Promise.all(
          CATEGORIES.map((cat) => listTickets({ category: cat, limit: 1 })),
        );

        if (cancelled) return;

        setCategoryCounts(
          CATEGORIES.map((category, i) => ({
            category,
            count: catResults[i]?.meta.total ?? 0,
          })),
        );
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load analytics.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const maxStatus = Math.max(...statusCounts.map((s) => s.count), 1);
  const maxCategory = Math.max(...categoryCounts.map((c) => c.count), 1);

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">Analytics</h2>
        <button
          onClick={() => setTick((t) => t + 1)}
          disabled={loading}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          aria-label="Refresh analytics"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
      )}

      {/* Summary card */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          Total tickets
        </p>
        <p className="mt-1 text-4xl font-bold tabular-nums text-slate-100">
          {totalTickets}
        </p>
      </div>

      {/* By status */}
      <section aria-label="Tickets by status">
        <h3 className="mb-3 text-sm font-semibold text-slate-400">By Status</h3>
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-4 space-y-3">
          {statusCounts.map(({ status, count }) => (
            <div key={status} className="space-y-1">
              <div className="flex justify-between text-xs text-slate-400">
                <span>{STATUS_LABELS[status]}</span>
                <span className="tabular-nums">{count}</span>
              </div>
              <div
                className="h-2 rounded-full bg-slate-700 overflow-hidden"
                role="progressbar"
                aria-valuenow={count}
                aria-valuemax={maxStatus}
                aria-label={`${STATUS_LABELS[status]}: ${count}`}
              >
                <div
                  className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                  style={{ width: `${(count / maxStatus) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* By category */}
      <section aria-label="Tickets by category">
        <h3 className="mb-3 text-sm font-semibold text-slate-400">By Category</h3>
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-4 space-y-3">
          {categoryCounts.map(({ category, count }) => {
            const style = DOMAIN_STYLES[category];
            return (
              <div key={category} className="space-y-1">
                <div className="flex justify-between text-xs text-slate-400">
                  <span>{style.label}</span>
                  <span className="tabular-nums">{count}</span>
                </div>
                <div
                  className="h-2 rounded-full bg-slate-700 overflow-hidden"
                  role="progressbar"
                  aria-valuenow={count}
                  aria-valuemax={maxCategory}
                  aria-label={`${style.label}: ${count}`}
                >
                  <div
                    className={`h-full rounded-full bg-${style.color}-500 transition-all duration-500`}
                    style={{ width: `${(count / maxCategory) * 100}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
