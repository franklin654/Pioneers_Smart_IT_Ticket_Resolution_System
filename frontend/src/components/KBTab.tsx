import React, { useState, useEffect, useRef, useMemo } from "react";
import { motion } from "motion/react";
import { Search, RefreshCw, CheckCircle2, Copy, Check, AlertTriangle } from "lucide-react";

interface KBTabProps {
  cases: any[];
  loading: boolean;
  onRefresh: () => void;
}

const DOMAIN_STYLES: Record<string, { color: string; bg: string; border: string }> = {
  infrastructure: { color: "text-sky-400", bg: "bg-sky-500/5", border: "border-sky-500/20" },
  application: { color: "text-purple-400", bg: "bg-purple-500/5", border: "border-purple-500/20" },
  security: { color: "text-rose-400", bg: "bg-rose-500/5", border: "border-rose-500/20" },
  database: { color: "text-amber-400", bg: "bg-amber-500/5", border: "border-amber-500/20" },
  network: { color: "text-cyan-400", bg: "bg-cyan-500/5", border: "border-cyan-500/20" },
  access_management: { color: "text-violet-400", bg: "bg-violet-500/5", border: "border-violet-500/20" },
};

const CATEGORIES = ["", "infrastructure", "application", "security", "database", "access_management", "network"];

function splitSteps(text: string | null | undefined): string[] {
  if (!text) return [];
  return text
    .split("\n")
    .map((s) => s.replace(/^[\d]+\.\s*|^[-•*]\s*/, "").trim())
    .filter(Boolean);
}

export default function KBTab({ cases, loading, onRefresh }: KBTabProps) {
  const [selectedCase, setSelectedCase] = useState<any | null>(null);
  const [selectedCaseDetail, setSelectedCaseDetail] = useState<any | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  // Abort controller to cancel in-flight case detail fetch on rapid selection (C-6)
  const abortRef = useRef<AbortController | null>(null);
  // Timeout ref for copiedIndex reset — cleared on unmount (W-7)
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset selection when the cases list is refreshed to avoid stale detail (C-7)
  useEffect(() => {
    setSelectedCase(null);
    setSelectedCaseDetail(null);
    setDetailError(null);
  }, [cases]);

  // Cleanup on unmount (W-7, C-6)
  useEffect(() => () => {
    if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    if (abortRef.current) abortRef.current.abort();
  }, []);

  const handleCaseSelect = async (c: any) => {
    // Cancel previous in-flight request (C-6)
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setSelectedCase(c);
    setSelectedCaseDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const res = await fetch(`/api/v1/tickets/${c.id}`, { signal: controller.signal });
      if (res.ok) {
        setSelectedCaseDetail(await res.json());
      } else {
        setDetailError(`Failed to load case details (HTTP ${res.status}).`);
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setDetailError("Could not load case details. Please try again.");
      }
    } finally {
      if (!controller.signal.aborted) setDetailLoading(false);
    }
  };

  const filtered = useMemo(() => {
    return cases.filter((c) => {
      const matchesQuery =
        !query ||
        c.title?.toLowerCase().includes(query.toLowerCase()) ||
        c.category?.toLowerCase().includes(query.toLowerCase());
      const matchesCat = !category || c.category === category;
      return matchesQuery && matchesCat;
    });
  }, [cases, query, category]);

  const handleCopy = (text: string, idx: number) => {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopiedIndex(idx);
    // Clear previous timer before setting new one (W-7)
    if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = setTimeout(() => setCopiedIndex(null), 2000);
  };

  return (
    <motion.div
      key="cases"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="grid grid-cols-1 lg:grid-cols-12 gap-6 w-full items-start"
    >
      {/* Left panel */}
      <div className="lg:col-span-5 flex flex-col gap-4">
        <div className="glass-container border border-white/10 rounded-2xl p-4 bg-black/40 shadow-xl flex flex-col gap-4 text-left">
          <div className="flex items-center justify-between pb-2 border-b border-white/5">
            <h3 className="text-xs uppercase font-mono tracking-widest text-slate-400 font-bold flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" /> Resolved Cases
            </h3>
            <div className="flex items-center gap-2">
              <span className="text-[9px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded font-mono font-bold">
                {cases.length} CASES
              </span>
              <button
                onClick={onRefresh}
                disabled={loading}
                className="p-1.5 rounded-lg bg-white/5 border border-white/5 text-slate-400 hover:text-white hover:border-white/10 transition-all cursor-pointer disabled:opacity-40"
                title="Refresh"
              >
                <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>

          <p className="text-xs text-slate-400 leading-normal">
            Auto-resolved tickets from the AI pipeline — a living reference of real solutions.
          </p>

          <div className="relative">
            <Search className="absolute left-3 top-2.5 w-3.5 h-3.5 text-slate-500" />
            <input
              type="text"
              placeholder="Filter by title or category..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full bg-slate-950/60 border border-white/10 rounded-xl py-2 pl-9 pr-3 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-400/50 transition-all font-sans"
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className={`text-[9px] font-mono px-2 py-1 rounded border transition-all cursor-pointer ${
                  category === cat
                    ? "bg-cyan-500/15 border-cyan-500/40 text-cyan-400 font-bold"
                    : "bg-white/5 border-white/5 text-slate-400 hover:text-slate-200"
                }`}
              >
                {cat ? cat.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "All"}
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-2 overflow-y-auto max-h-[380px] pr-1">
            {loading ? (
              <div className="flex items-center justify-center py-12 gap-2 text-slate-500 font-mono text-xs">
                <span className="w-4 h-4 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
                Loading resolved cases...
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-16 text-slate-600 font-mono text-xs">
                {cases.length === 0 ? "No auto-resolved tickets yet." : "No matches found."}
              </div>
            ) : (
              filtered.map((c) => {
                const isSelected = selectedCase?.id === c.id;
                const catStyle = DOMAIN_STYLES[c.category] || DOMAIN_STYLES.infrastructure;
                return (
                  <div
                    key={c.id}
                    onClick={() => handleCaseSelect(c)}
                    className={`p-3 rounded-xl border transition-all cursor-pointer text-left ${
                      isSelected
                        ? "bg-cyan-950/20 border-cyan-500/40 shadow-[0_0_12px_rgba(34,211,238,0.06)]"
                        : "bg-black/20 border-white/5 hover:border-slate-800"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`text-[8px] uppercase font-mono px-1.5 py-0.5 rounded border ${catStyle.color} ${catStyle.bg} ${catStyle.border}`}>
                        {c.category?.replace("_", " ")}
                      </span>
                      <span className="text-[8px] font-mono text-slate-600">
                        {c.id?.slice(0, 8)}…
                      </span>
                    </div>
                    <h4 className="text-xs font-semibold text-slate-200 truncate">{c.title}</h4>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Right panel */}
      <div className="lg:col-span-7 flex flex-col gap-4 text-left">
        {selectedCase ? (
          <div className="glass-container border border-white/10 rounded-2xl p-5 bg-black/40 shadow-xl flex flex-col gap-5">
            {/* Header — always available from TicketSummary */}
            <div className="flex items-start justify-between border-b border-white/5 pb-3 gap-3">
              <div className="flex flex-col gap-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[9px] font-mono text-emerald-400 uppercase font-bold tracking-widest">
                    Auto-Resolved Case
                  </span>
                  <span className="text-[8px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded font-mono font-bold">
                    ✓ Verified
                  </span>
                  {selectedCaseDetail?.resolution?.llm_quality_score != null && (
                    <span className="text-[8px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded font-mono font-bold">
                      Score: {selectedCaseDetail.resolution.llm_quality_score.toFixed(1)}/5
                    </span>
                  )}
                </div>
                <h2 className="text-sm font-semibold text-white">{selectedCase.title}</h2>
              </div>
              <span className="text-[9px] text-slate-500 font-mono shrink-0">
                {selectedCase.id?.slice(0, 8)}…
              </span>
            </div>

            {/* Loading state */}
            {detailLoading && (
              <div className="flex items-center justify-center py-8 gap-2 text-slate-500 font-mono text-xs">
                <span className="w-4 h-4 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
                Loading case details...
              </div>
            )}

            {/* Error state — shown when detail fetch fails (W-6) */}
            {detailError && !detailLoading && (
              <div className="flex items-center gap-2 bg-rose-950/20 border border-rose-500/20 rounded-xl px-3 py-3 text-xs text-rose-300 font-sans">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-rose-400" />
                <span>{detailError}</span>
              </div>
            )}

            {/* Detail content — only rendered once full TicketDetailResponse is available */}
            {selectedCaseDetail && !detailLoading && (
              <>
                {selectedCaseDetail.classification && (
                  <div className="flex items-center gap-2 flex-wrap text-[9px] font-mono">
                    <span className="text-slate-500 uppercase font-bold">Category:</span>
                    <span className={`${(DOMAIN_STYLES[selectedCaseDetail.classification.predicted_category] || DOMAIN_STYLES.infrastructure).color} font-bold capitalize`}>
                      {selectedCaseDetail.classification.predicted_category?.replace(/_/g, " ")}
                    </span>
                    {selectedCaseDetail.classification.confidence != null && (
                      <>
                        <span className="text-slate-600">·</span>
                        <span className="text-slate-400">
                          Confidence: {(selectedCaseDetail.classification.confidence * 100).toFixed(0)}%
                        </span>
                      </>
                    )}
                  </div>
                )}

                <div className="flex flex-col gap-1">
                  <span className="text-[9px] font-mono text-slate-500 uppercase tracking-wider font-semibold">Original Incident</span>
                  <p className="text-xs text-slate-300 bg-black/35 border border-white/5 p-3 rounded-xl font-sans leading-relaxed select-text">
                    {selectedCaseDetail.description}
                  </p>
                </div>

                {(() => {
                  const steps = splitSteps(selectedCaseDetail.resolution?.suggested_steps);
                  return steps.length > 0 ? (
                    <div className="flex flex-col gap-3">
                      <span className="text-[9px] font-mono text-violet-400 uppercase tracking-wider font-bold">
                        ✓ AI Resolution Steps
                      </span>
                      <div className="flex flex-col gap-2">
                        {steps.map((step, idx) => (
                          <div
                            key={idx}
                            className="p-3 bg-white/[0.02] border border-white/5 rounded-xl flex items-start justify-between gap-3 group hover:border-violet-500/30 transition-all"
                          >
                            <div className="flex gap-3 items-start min-w-0">
                              <span className="w-5 h-5 rounded-full bg-violet-500/10 border border-violet-500/25 text-violet-400 text-[9px] font-mono font-bold flex items-center justify-center shrink-0 mt-0.5">
                                {idx + 1}
                              </span>
                              <p className="text-xs text-slate-200 leading-relaxed font-sans select-text">{step}</p>
                            </div>
                            <button
                              onClick={() => handleCopy(step, idx)}
                              className="p-1.5 rounded-lg bg-black/40 border border-white/5 text-slate-400 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer shrink-0"
                              title="Copy step"
                            >
                              {copiedIndex === idx ? (
                                <Check className="w-3.5 h-3.5 text-emerald-400" />
                              ) : (
                                <Copy className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null;
                })()}

                {/* Knowledge sources — use entry_id not ticket_id (C-2) */}
                {selectedCaseDetail.resolution?.retrieved_tickets?.length > 0 && (
                  <div className="flex flex-col gap-2">
                    <span className="text-[9px] font-mono text-slate-500 uppercase tracking-wider font-semibold">
                      Knowledge Sources Used
                    </span>
                    <div className="flex flex-col gap-1.5">
                      {selectedCaseDetail.resolution.retrieved_tickets.slice(0, 3).map((rt: any, i: number) => (
                        <div key={i} className="flex items-center justify-between bg-black/30 border border-white/5 rounded-lg px-3 py-2 text-xs">
                          <span className="text-slate-300 font-sans truncate">{rt.title || rt.entry_id}</span>
                          {rt.similarity_score != null && (
                            <span className="text-[9px] font-mono text-cyan-400 ml-2 shrink-0">
                              {(rt.similarity_score * 100).toFixed(0)}% sim
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        ) : (
          <div className="glass-container border border-dashed border-white/10 rounded-2xl p-16 text-center bg-black/20 select-none">
            <CheckCircle2 className="w-10 h-10 text-slate-700 mx-auto mb-3.5 animate-pulse" />
            <h3 className="font-bold uppercase tracking-wider text-slate-400 font-mono text-xs">No Case Selected</h3>
            <p className="font-sans text-xs text-slate-500 max-w-xs mx-auto mt-2 leading-relaxed">
              Select a resolved case from the list to view its AI-generated runbook steps and knowledge sources.
            </p>
          </div>
        )}
      </div>
    </motion.div>
  );
}
