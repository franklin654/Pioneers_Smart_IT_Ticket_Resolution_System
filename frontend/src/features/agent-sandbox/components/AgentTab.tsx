import { useState } from "react";
import { CATEGORIES, DOMAIN_STYLES } from "../../../shared/constants";
import type { Category } from "../../../types";

interface AgentTrace {
  agent: string;
  input: string;
  output: string;
  latency_ms: number;
  error: string | null;
}

interface RunResult {
  ticket_id: string;
  traces: AgentTrace[];
  final_status: string;
}

export function AgentTab() {
  const [text, setText] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [result, setResult] = useState<RunResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runSandbox() {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/v1/sandbox/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionStorage.getItem("token") ?? ""}`,
        },
        body: JSON.stringify({
          description: text.trim(),
          category: category || undefined,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as { data: RunResult };
      setResult(json.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">Agent Sandbox</h2>
        <p className="mt-1 text-sm text-slate-500">
          Run the full agent pipeline on ad-hoc text without creating a ticket.
          Useful for testing classification, retrieval, and generation.
        </p>
      </div>

      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-4 space-y-4">
        <div>
          <label
            htmlFor="sandbox-text"
            className="mb-1 block text-sm text-slate-300"
          >
            Issue description
          </label>
          <textarea
            id="sandbox-text"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Describe an IT issue to test the pipeline…"
            className="w-full resize-y rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          />
        </div>

        <div className="flex items-center gap-3">
          <label htmlFor="sandbox-category" className="text-sm text-slate-300">
            Force category
          </label>
          <select
            id="sandbox-category"
            value={category}
            onChange={(e) => setCategory(e.target.value as Category | "")}
            className="rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          >
            <option value="">Auto-classify</option>
            {CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {DOMAIN_STYLES[cat].label}
              </option>
            ))}
          </select>

          <button
            onClick={() => void runSandbox()}
            disabled={loading || !text.trim()}
            className="ml-auto rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {loading ? "Running…" : "Run pipeline"}
          </button>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-3" aria-live="polite">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-300">Trace</h3>
            <span className="text-xs font-mono text-slate-500">
              {result.final_status}
            </span>
          </div>

          {result.traces.map((trace, i) => (
            <details
              key={i}
              className="rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)]"
            >
              <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-sm">
                <span className="font-medium text-slate-200">{trace.agent}</span>
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  <span>{trace.latency_ms} ms</span>
                  {trace.error && (
                    <span className="text-rose-400">error</span>
                  )}
                </div>
              </summary>
              <div className="border-t border-[var(--color-border)] px-4 py-3 space-y-3">
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-slate-500">
                    Input
                  </p>
                  <pre className="overflow-x-auto rounded bg-slate-800 p-3 text-xs text-slate-300 whitespace-pre-wrap">
                    {trace.input}
                  </pre>
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-slate-500">
                    Output
                  </p>
                  <pre className="overflow-x-auto rounded bg-slate-800 p-3 text-xs text-slate-300 whitespace-pre-wrap">
                    {trace.output}
                  </pre>
                </div>
                {trace.error && (
                  <p className="text-xs text-rose-400">{trace.error}</p>
                )}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
