import React from "react";
import { motion } from "motion/react";
import { Sparkles, Activity, Server, Shield, Database, Layers, Cpu } from "lucide-react";
import CoreParticleCanvas from "./CoreParticleCanvas";

interface AgentTabProps {
  activeTicket: any;
  isPolling: boolean;
  triggerDecompose: boolean;
  setTriggerDecompose: (v: boolean) => void;
}

const PARTICLE_LEGEND_MAP: Record<string, { title: string; desc: string; geo: string }> = {
  none: {
    title: "NEUTRAL STANDBY",
    geo: "Concentric Sphere",
    desc: "Baseline: Neural vectors are locked at nominal idle orbits, awaiting incoming incident pipeline signals.",
  },
  new: {
    title: "NEUTRAL STANDBY",
    geo: "Concentric Sphere",
    desc: "Baseline: Neural vectors are locked at nominal idle orbits, awaiting incoming incident pipeline signals.",
  },
  classifying: {
    title: "DE-ASSEMBLY & PRIVACY SHIELDS",
    geo: "Decomposing Scattered Cloud",
    desc: "PII Scrubbing: Dismantling plaintext inputs. Stripping sensitive tokens, credential paths, and variables into generic weights.",
  },
  classified: {
    title: "SOFTMAX ROUTING CLUSTERS",
    geo: "Grouped Spatial Ensembles",
    desc: "Multi-Domain Classification: Segmenting coordinates into dense zones corresponding to network, database, application, or security clusters.",
  },
  retrieving: {
    title: "COSINE SIMILARITY VECTOR SEARCH",
    geo: "Linear Gravity Vortex",
    desc: "Index Scanning: Pulling corresponding runbooks out of high-dimension database coordinates with similarity indices.",
  },
  generating: {
    title: "HEURISTIC RUNBOOK SYNTHESIS",
    geo: "Logarithmic Galaxy Spiral",
    desc: "AI Synthesis: Compounding matched guidelines under deep flash inference, rendering custom draft runbook checklists.",
  },
  evaluating: {
    title: "CONSTRAINTS AUDIT GRID",
    geo: "Orthogonal Hypercube Grid",
    desc: "Validation Judge: Executing parallel dual-guard auditing to ensure the compiled steps are factual, actionable, and secure.",
  },
  auto_resolved: {
    title: "AUTONOMOUS EMBEDDED GATEWAYS",
    geo: "Crystalline Emerald Core",
    desc: "Cleared Route: Solved runbook locked inside persistent vector layers, safely routed to auto-resolve.",
  },
  assigned: {
    title: "DOWNSTREAM ENGINEERING PIPE",
    geo: "Concurrently Arrayed Lines",
    desc: "Queue Redirection: Aligning coordinates with standard team sprint registers to assign designated manual engineering paths.",
  },
  escalated: {
    title: "L2 ESCALATION CRITICAL ANOMALY",
    geo: "Dual-Opposing Polar Shells",
    desc: "Intervention Lock: Critical warning orbit flagging immediate required human assistance overrides.",
  },
  closed: {
    title: "COMMITTED KNOWLEDGE BASE",
    geo: "Crystalline Emerald Core",
    desc: "Solved Runbook: Verified resolution steps approved by staff operator, mapped to evergreen global index registers.",
  },
  reopened: {
    title: "NEUTRAL STANDBY",
    geo: "Concentric Sphere",
    desc: "Re-queued: Ticket re-opened for reprocessing — neural vectors returning to idle standby.",
  },
};

// Collapsed STATUS_TIMELINE — three routing outcomes share one "Routed" entry (C-4)
const STATUS_TIMELINE = [
  { key: "new", label: "New" },
  { key: "classifying", label: "Classify" },
  { key: "classified", label: "Classified" },
  { key: "retrieving", label: "Retrieve" },
  { key: "generating", label: "Generate" },
  { key: "evaluating", label: "Evaluate" },
  { key: "routed", label: "Routed" },
];

// True terminal statuses — "resolved" does not exist in the backend enum (C-1)
const TERMINAL_STATUSES = ["auto_resolved", "assigned", "escalated", "closed"];

// Maps current status to its ordinal position in the pipeline (I-4: reopened → 0)
function statusIndex(status: string): number {
  const order = ["new", "classifying", "classified", "retrieving", "generating", "evaluating"];
  const idx = order.indexOf(status);
  if (idx >= 0) return idx;
  if (TERMINAL_STATUSES.includes(status)) return order.length; // 6 = all steps past
  if (status === "reopened") return 0;
  return -1;
}

export default function AgentTab({ activeTicket, isPolling, triggerDecompose, setTriggerDecompose }: AgentTabProps) {
  const currentStatus = activeTicket ? activeTicket.status : "none";
  const legend = PARTICLE_LEGEND_MAP[currentStatus] || PARTICLE_LEGEND_MAP.none;
  const currentIdx = statusIndex(currentStatus);
  const isTerminal = TERMINAL_STATUSES.includes(currentStatus);

  const classification = activeTicket?.classification;
  const resolution = activeTicket?.resolution;

  return (
    <motion.div
      key="agent"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="grid grid-cols-1 lg:grid-cols-12 gap-8 w-full items-start text-left"
    >
      {/* Left: Particle canvas */}
      <div className="lg:col-span-5 flex flex-col gap-4">
        <div className="glass-container border border-white/10 rounded-2xl relative overflow-hidden flex flex-col bg-black/45 h-[350px] shrink-0">
          <div className="absolute inset-0 z-0">
            <CoreParticleCanvas
              status={currentStatus}
              routingPath={activeTicket?.resolution?.routing_decision || "none"}
              triggerDecompose={triggerDecompose}
            />
          </div>

          <div className="absolute top-4 left-4 z-10 flex flex-col pointer-events-none text-left font-mono">
            <span className="text-[8px] uppercase tracking-widest text-cyan-400 font-bold bg-black/55 border border-white/10 px-2 py-0.5 rounded">
              High-Dimension Vector Projections
            </span>
            <span className="text-xs font-semibold text-white tracking-wider mt-1.5 inline-flex items-center gap-1.5 uppercase">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              {legend.title}
            </span>
          </div>

          <div className="absolute top-4 right-4 z-10 flex flex-col items-end gap-2 text-right">
            <button
              onClick={() => {
                setTriggerDecompose(true);
                setTimeout(() => setTriggerDecompose(false), 500);
              }}
              className="py-1 px-3 rounded-lg border border-red-500/30 bg-red-950/20 text-[9px] text-red-400 hover:bg-red-500/25 font-mono tracking-widest uppercase transition-all shadow-lg cursor-pointer pointer-events-auto"
            >
              De-stabilize
            </button>
            <span className="text-[8.5px] font-mono bg-cyan-950/45 border border-cyan-500/25 text-cyan-400 px-2 py-0.5 rounded font-bold uppercase select-none">
              {legend.geo}
            </span>
          </div>

          <div className="absolute bottom-4 left-4 right-4 z-10 pointer-events-none bg-black/75 border border-white/5 backdrop-blur-sm p-3 rounded-xl text-left">
            <p className="text-[11px] text-slate-400 leading-normal italic font-sans">
              "{legend.desc}"
            </p>
          </div>
        </div>

        <div className="bg-white/[0.01] border border-white/5 rounded-2xl p-4 font-sans text-xs text-slate-400 leading-relaxed flex flex-col gap-2">
          <span className="text-[9px] font-mono text-slate-500 uppercase font-bold tracking-wider">Holographic Particle Interface</span>
          <p>
            This sandbox maps incident features to spatial vectors. Changes in active agent tasks dynamically translate geometry anchors.
          </p>
        </div>
      </div>

      {/* Right: Analysis panels */}
      <div className="lg:col-span-7 flex flex-col gap-4">

        {/* Pipeline timeline — no deduplication, single Routed entry (C-4) */}
        <div className="glass-container border border-white/10 rounded-2xl p-4 bg-black/40 shadow-xl flex flex-col gap-3">
          <div className="flex justify-between items-center border-b border-white/5 pb-2">
            <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400 font-bold flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-cyan-400" /> Processing Timeline
            </span>
            <span className={`text-[8px] font-mono uppercase font-bold px-2 py-0.5 rounded border ${
              isPolling
                ? "text-cyan-400 border-cyan-500/30 bg-cyan-500/5 animate-pulse"
                : "text-slate-400 border-white/5 bg-white/5"
            }`}>
              {activeTicket ? currentStatus.replace(/_/g, " ") : "Awaiting"}
            </span>
          </div>

          {activeTicket ? (
            <div className="relative flex flex-col gap-1">
              {STATUS_TIMELINE.map((step, idx) => {
                const isRoutedStep = step.key === "routed";

                let state: "done" | "active" | "pending" = "pending";
                if (isRoutedStep) {
                  state = isTerminal ? "done" : "pending";
                } else {
                  if (isTerminal || currentIdx > idx) state = "done";
                  else if (currentIdx === idx) state = "active";
                }

                const displayLabel = isRoutedStep
                  ? isTerminal
                    ? currentStatus.replace(/_/g, " ").toUpperCase()
                    : "Awaiting Route"
                  : step.label;

                return (
                  <div key={step.key} className="flex items-center gap-3">
                    <div className={`w-5 h-5 rounded-full border text-[8px] font-mono font-bold flex items-center justify-center shrink-0 transition-all duration-300 ${
                      state === "done"
                        ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-400"
                        : state === "active"
                          ? "bg-cyan-500/20 border-cyan-400 text-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.3)] animate-pulse"
                          : "bg-black/40 border-white/10 text-slate-600"
                    }`}>
                      {state === "done" ? "✓" : idx + 1}
                    </div>
                    <span className={`text-[10px] font-mono font-medium ${
                      state === "done" ? "text-emerald-400" : state === "active" ? "text-cyan-400 font-bold" : "text-slate-600"
                    }`}>
                      {displayLabel}
                    </span>
                    {state === "active" && isPolling && (
                      <span className="text-[9px] text-cyan-400 font-mono animate-pulse">processing…</span>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-center py-6 text-slate-600 font-mono text-xs">Select a ticket to view pipeline progress.</div>
          )}
        </div>

        {/* Classification analysis */}
        {classification && (
          <div className="glass-container border border-white/10 rounded-2xl p-4 bg-black/40 shadow-xl flex flex-col gap-3">
            <div className="flex justify-between items-center border-b border-white/5 pb-2">
              <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400 font-bold">
                Classification Analysis
              </span>
              <div className="flex items-center gap-2">
                {classification.is_multi_domain && (
                  <span className="text-[8px] font-mono bg-amber-500/10 border border-amber-500/30 text-amber-400 px-1.5 py-0.5 rounded uppercase">
                    Multi-Domain
                  </span>
                )}
                <span className={`text-[8px] font-mono font-bold uppercase px-1.5 py-0.5 rounded border ${
                  classification.confidence_level === "high"
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                    : classification.confidence_level === "medium"
                      ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                      : "bg-rose-500/10 border-rose-500/30 text-rose-400"
                }`}>
                  {classification.confidence_level}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-black/30 border border-white/5 p-2 rounded-xl">
                <span className="text-[7px] text-slate-500 uppercase block font-bold font-mono">Predicted Category</span>
                <span className="font-semibold text-cyan-400 capitalize">
                  {classification.predicted_category?.replace(/_/g, " ")}
                </span>
              </div>
              <div className="bg-black/30 border border-white/5 p-2 rounded-xl">
                <span className="text-[7px] text-slate-500 uppercase block font-bold font-mono">Confidence</span>
                <span className="font-semibold text-white">
                  {((Number.isFinite(classification.confidence) ? classification.confidence : 0) * 100).toFixed(0)}%
                </span>
              </div>
            </div>

            {classification.top_categories?.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="text-[8px] font-mono text-slate-500 uppercase font-bold">Category Probabilities</span>
                {classification.top_categories.slice(0, 4).map((tc: any, i: number) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-[8px] font-mono text-slate-400 w-24 shrink-0 capitalize">
                      {tc.category?.replace(/_/g, " ")}
                    </span>
                    <div className="flex-grow bg-white/5 rounded-full h-1.5">
                      <div
                        className="bg-cyan-500/60 h-1.5 rounded-full transition-all duration-500"
                        style={{ width: `${(tc.probability * 100).toFixed(0)}%` }}
                      />
                    </div>
                    <span className="text-[8px] font-mono text-slate-500 w-8 text-right">
                      {(tc.probability * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Resolution details */}
        {resolution && (
          <div className="glass-container border border-white/10 rounded-2xl p-4 bg-black/40 shadow-xl flex flex-col gap-3">
            <div className="flex justify-between items-center border-b border-white/5 pb-2">
              <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400 font-bold">
                Resolution Details
              </span>
              <span className={`text-[9px] font-mono font-bold px-2 py-0.5 rounded border uppercase ${
                resolution.routing_decision === "auto_resolved"
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                  : resolution.routing_decision === "escalated"
                    ? "bg-rose-500/10 border-rose-500/30 text-rose-400"
                    : "bg-blue-500/10 border-blue-500/30 text-blue-400"
              }`}>
                {resolution.routing_decision?.replace(/_/g, " ")}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              {resolution.llm_quality_score != null && (
                <div className="bg-black/30 border border-white/5 p-2 rounded-xl">
                  <span className="text-[7px] text-slate-500 uppercase block font-bold font-mono">Quality Score</span>
                  <span className="font-semibold text-amber-400">
                    {resolution.llm_quality_score.toFixed(1)} / 5.0
                  </span>
                </div>
              )}
              {resolution.assigned_department && (
                <div className="bg-black/30 border border-white/5 p-2 rounded-xl">
                  <span className="text-[7px] text-slate-500 uppercase block font-bold font-mono">Assigned To</span>
                  <span className="font-semibold text-blue-400">{resolution.assigned_department}</span>
                </div>
              )}
              {resolution.is_repeated_issue && (
                <div className="bg-amber-950/20 border border-amber-500/20 p-2 rounded-xl">
                  <span className="text-[7px] text-amber-400 uppercase block font-bold font-mono">Repeated Issue</span>
                  <span className="text-amber-300 font-semibold">Yes</span>
                </div>
              )}
            </div>

            {resolution.escalation_reason && (
              <div className="bg-rose-950/20 border border-rose-500/20 rounded-xl p-3 text-xs text-rose-300 font-sans">
                <span className="font-bold text-rose-400">Escalation: </span>
                {resolution.escalation_reason}
              </div>
            )}

            {/* Knowledge sources — use entry_id not ticket_id (C-2) */}
            {resolution.retrieved_tickets?.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="text-[8px] font-mono text-slate-500 uppercase font-bold">Knowledge Sources</span>
                {resolution.retrieved_tickets.slice(0, 3).map((rt: any, i: number) => (
                  <div key={i} className="flex items-center justify-between bg-black/30 border border-white/5 rounded-lg px-3 py-1.5 text-xs">
                    <span className="text-slate-300 font-sans truncate">{rt.title || rt.entry_id}</span>
                    {rt.similarity_score != null && (
                      <span className="text-[9px] font-mono text-cyan-400 ml-2 shrink-0">
                        {(rt.similarity_score * 100).toFixed(0)}% sim
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {!activeTicket && (
          <div className="glass-container border border-dashed border-white/10 rounded-2xl p-12 text-center bg-black/20 select-none">
            <Activity className="w-10 h-10 text-slate-700 mx-auto mb-3 animate-pulse" />
            <h3 className="font-bold uppercase tracking-wider text-slate-400 font-mono text-xs">No Ticket Selected</h3>
            <p className="font-sans text-xs text-slate-500 max-w-sm mx-auto mt-2 leading-relaxed">
              Select a ticket from the Resolution tab to view classification and processing details here.
            </p>
          </div>
        )}
      </div>
    </motion.div>
  );
}
