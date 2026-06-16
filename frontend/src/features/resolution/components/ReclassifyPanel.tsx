import { useState } from "react";
import type { Category, Resolution } from "../../../types";
import { CATEGORIES, DOMAIN_STYLES } from "../../../shared/constants";

interface Props {
  escalationReason: Resolution["escalation_reason"];
  onSubmit: (category: Category) => Promise<void>;
}

export function ReclassifyPanel({ escalationReason, onSubmit }: Props) {
  const [selected, setSelected] = useState<Category>("infrastructure");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await onSubmit(selected);
    } catch {
      setError("Failed to submit reclassification. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section
      aria-label="Reclassify ticket"
      className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 space-y-4"
    >
      <div>
        <h3 className="font-medium text-amber-300">Awaiting Human Review</h3>
        {escalationReason && (
          <p className="mt-1 text-sm text-slate-400" role="alert">
            {escalationReason}
          </p>
        )}
      </div>

      <form onSubmit={(e) => void handleSubmit(e)}>
        <div className="mb-3">
          <label
            htmlFor="reclassify-category"
            className="mb-1 block text-sm text-slate-300"
          >
            Correct category
          </label>
          <select
            id="reclassify-category"
            value={selected}
            onChange={(e) => setSelected(e.target.value as Category)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            {CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {DOMAIN_STYLES[cat].label}
              </option>
            ))}
          </select>
        </div>

        {error && (
          <p role="alert" className="mb-3 text-sm text-rose-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-amber-500"
        >
          {loading ? "Submitting…" : "Submit reclassification"}
        </button>
      </form>
    </section>
  );
}
