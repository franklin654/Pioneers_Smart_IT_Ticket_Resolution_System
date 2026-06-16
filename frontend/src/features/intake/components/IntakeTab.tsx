import type { FormEvent } from "react";
import { useIngestTicket } from "../hooks/useIngestTicket";
import { CATEGORIES, DOMAIN_STYLES } from "../../../shared/constants";
import type { Category } from "../../../types";

export function IntakeTab() {
  const { form, setForm, result, loading, error, submit } = useIngestTicket();

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    void submit();
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Submit New Ticket</h2>

      <form
        onSubmit={handleSubmit}
        noValidate
        aria-label="Submit new ticket"
        className="space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-6"
      >
        {/* Title */}
        <div>
          <label htmlFor="ticket-title" className="mb-1 block text-sm text-slate-300">
            Title <span aria-hidden="true">*</span>
          </label>
          <input
            id="ticket-title"
            type="text"
            required
            maxLength={255}
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="w-full rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            placeholder="Brief summary of the issue"
          />
        </div>

        {/* Description */}
        <div>
          <label htmlFor="ticket-description" className="mb-1 block text-sm text-slate-300">
            Description <span aria-hidden="true">*</span>
          </label>
          <textarea
            id="ticket-description"
            required
            rows={5}
            maxLength={10000}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className="w-full resize-y rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            placeholder="Describe the issue in detail…"
          />
        </div>

        {/* Priority */}
        <div>
          <label htmlFor="ticket-priority" className="mb-1 block text-sm text-slate-300">
            Priority
          </label>
          <select
            id="ticket-priority"
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
            className="rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            <option value={1}>1 – Critical</option>
            <option value={2}>2 – High</option>
            <option value={3}>3 – Medium</option>
            <option value={4}>4 – Low</option>
            <option value={5}>5 – Minimal</option>
          </select>
        </div>

        {/* Optional category */}
        <div>
          <label htmlFor="ticket-category" className="mb-1 block text-sm text-slate-300">
            Category{" "}
            <span className="text-slate-500">(optional — auto-detected if omitted)</span>
          </label>
          <select
            id="ticket-category"
            value={form.category}
            onChange={(e) =>
              setForm({ ...form, category: e.target.value as Category | "" })
            }
            className="rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            <option value="">Auto-detect</option>
            {CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {DOMAIN_STYLES[cat].label}
              </option>
            ))}
          </select>
        </div>

        {error && (
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading || !form.title.trim() || !form.description.trim()}
          className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          {loading ? "Submitting…" : "Submit ticket"}
        </button>
      </form>

      {result && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm"
        >
          <p className="font-medium text-emerald-300">Ticket queued successfully!</p>
          <p className="mt-1 text-slate-400">
            ID: <span className="font-mono text-xs">{result.ticket_id}</span>
          </p>
          <p className="text-slate-400">{result.message}</p>
        </div>
      )}
    </div>
  );
}
