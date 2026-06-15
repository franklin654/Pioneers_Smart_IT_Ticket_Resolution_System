import React from "react";
import { motion } from "motion/react";
import {
  Sliders,
  RefreshCw,
  ShieldAlert,
  Activity,
  Shield,
  Database,
  Server,
  Layers,
  Cpu,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";

interface ResolutionTabProps {
  ticketsList: any[];
  activeTicketId: string | null;
  onSelectTicket: (id: string, ticket: any) => void;
  activeTicket: any;
  isPolling: boolean;
  editedStepsText: string;
  setEditedStepsText: (v: string) => void;
  operatorName: string;
  setOperatorName: (v: string) => void;
  handleResolveFeedback: (type: "accepted" | "modified" | "rejected") => void;
  feedbackSubmitting: boolean;
}

const DOMAIN_STYLES: Record<string, { color: string; bg: string; border: string; icon: any }> = {
  infrastructure: { color: "text-sky-400", bg: "bg-sky-500/5", border: "border-sky-500/20", icon: Server },
  application: { color: "text-purple-400", bg: "bg-purple-500/5", border: "border-purple-500/20", icon: Layers },
  security: { color: "text-rose-400", bg: "bg-rose-500/5", border: "border-rose-500/20", icon: Shield },
  database: { color: "text-amber-400", bg: "bg-amber-500/5", border: "border-amber-500/20", icon: Database },
  network: { color: "text-cyan-400", bg: "bg-cyan-500/5", border: "border-cyan-500/20", icon: Cpu },
  access_management: { color: "text-violet-400", bg: "bg-violet-500/5", border: "border-violet-500/20", icon: Shield },
};

const STATUS_STEPS = [
  { label: "Intake" },
  { label: "Classify" },
  { label: "Retrieve" },
  { label: "Generate" },
  { label: "Evaluate" },
  { label: "Routed" },
];

// Maps a live status to the index of the currently active pipeline step (C-3)
const STATUS_STEP_MAP: Record<string, number> = {
  new: 0,
  classifying: 1,
  classified: 1,
  retrieving: 2,
  generating: 3,
  evaluating: 4,
  reopened: 0,
};

// True terminal statuses from backend TicketStatus enum — "resolved" does not exist (C-1)
const TERMINAL_STATUSES = ["auto_resolved", "assigned", "escalated", "closed"];

function splitSteps(text: string | null | undefined): string[] {
  if (!text) return [];
  return text
    .split("\n")
    .map((s) => s.replace(/^[\d]+\.\s*|^[-•*]\s*/, "").trim())
    .filter(Boolean);
}

function ConfidenceLevelBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    high: "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
    medium: "bg-amber-500/10 border-amber-500/30 text-amber-400",
    low: "bg-rose-500/10 border-rose-500/30 text-rose-400",
  };
  return (
    <span className={`text-[8px] font-mono font-bold uppercase px-1.5 py-0.5 rounded border ${styles[level] || styles.medium}`}>
      {level}
    </span>
  );
}

export default function ResolutionTab({
  ticketsList,
  activeTicketId,
  onSelectTicket,
  activeTicket,
  isPolling,
  editedStepsText,
  setEditedStepsText,
  operatorName,
  setOperatorName,
  handleResolveFeedback,
  feedbackSubmitting,
}: ResolutionTabProps) {
  return (
    <motion.div
      key="resolution"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="grid grid-cols-1 lg:grid-cols-12 gap-6 w-full items-start"
    >
      {/* Left: Queue */}
      <div className="lg:col-span-4 flex flex-col gap-4">
        <div className="glass-container border border-white/10 rounded-2xl p-4 shadow-lg flex flex-col gap-3 bg-black/35 text-left">
          <div className="flex justify-between items-center pb-2 border-b border-white/5 select-none">
            <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400 font-bold flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-cyan-400" /> Incident Triage Queue
            </span>
            <span className="text-[10px] bg-white/5 border border-white/5 px-2 py-0.5 rounded text-slate-400 font-mono">
              {ticketsList.length} Active
            </span>
          </div>

          <div className="flex flex-col gap-2 max-h-[500px] overflow-y-auto pr-1">
            {ticketsList.length === 0 ? (
              <div className="text-center py-12 text-slate-600 font-mono text-xs">Awaiting initial triggers...</div>
            ) : (
              ticketsList.map((tick) => {
                const isSelected = activeTicketId === tick.id;
                const catStyle = DOMAIN_STYLES[tick.category] || DOMAIN_STYLES.infrastructure;
                const isTicketPolling = isPolling && activeTicketId === tick.id;
                const isTerminal = TERMINAL_STATUSES.includes(tick.status);

                return (
                  <div
                    key={tick.id}
                    onClick={() => onSelectTicket(tick.id, tick)}
                    className={`p-3 rounded-xl border transition-all cursor-pointer flex items-center justify-between gap-3 ${
                      isSelected
                        ? "bg-cyan-950/20 border-cyan-500/40 shadow-[0_0_12px_rgba(34,211,238,0.06)]"
                        : "bg-black/20 border-white/5 hover:border-slate-800"
                    }`}
                  >
                    <div className="flex flex-col gap-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-[9px] font-mono text-slate-500 font-bold truncate max-w-[80px]">
                          {tick.id?.slice(0, 8)}…
                        </span>
                        <span className={`text-[7px] uppercase font-mono px-1.5 py-0.5 rounded border ${catStyle.color} ${catStyle.bg} ${catStyle.border}`}>
                          {tick.category?.replace("_", " ")}
                        </span>
                      </div>
                      <h4 className="text-[12px] font-semibold text-slate-200 truncate">{tick.title}</h4>
                    </div>
                    <span className={`text-[8px] uppercase tracking-wider font-mono px-1.5 py-0.5 rounded shrink-0 border ${
                      isTicketPolling
                        ? "text-cyan-400 border-cyan-500/30 bg-cyan-500/5 animate-pulse"
                        : isTerminal
                          ? tick.status === "auto_resolved"
                            ? "text-emerald-400 border-emerald-500/20 bg-emerald-500/5"
                            : tick.status === "escalated"
                              ? "text-rose-400 border-rose-500/20 bg-rose-500/5"
                              : "text-blue-400 border-blue-500/20 bg-blue-500/5"
                          : "text-slate-400 border-white/5 bg-white/5"
                    }`}>
                      {isTicketPolling ? "PROCESSING" : tick.status.replace(/_/g, " ")}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Right: Work Desk */}
      <div className="lg:col-span-8 flex flex-col gap-6 text-left">
        {activeTicket ? (
          <div className="glass-container border border-white/10 rounded-2xl p-5 bg-black/40 shadow-xl flex flex-col gap-5">

            {/* Pipeline Stepper — index-based logic avoids false "done" states (C-3) */}
            <div className="bg-white/[0.02] border border-white/5 rounded-2xl p-4 flex flex-col gap-3 font-mono text-[9px] text-slate-400 select-none">
              <div className="flex justify-between items-center">
                <span className="uppercase text-slate-400 font-bold tracking-wider text-[8px]">Pipeline Progression</span>
                <span className="text-[8px] bg-cyan-950/40 text-cyan-400 border border-cyan-500/10 px-2 py-0.5 rounded font-bold uppercase">
                  {activeTicket.status?.replace(/_/g, " ")}
                </span>
              </div>
              <div className="grid grid-cols-6 gap-1 mt-1">
                {(() => {
                  const isTerminal = TERMINAL_STATUSES.includes(activeTicket.status);
                  // When terminal all 6 steps are done (index 6 > any step 0-5)
                  const currentStepIdx = isTerminal ? 6 : (STATUS_STEP_MAP[activeTicket.status] ?? 0);

                  return STATUS_STEPS.map((step, idx) => {
                    const isDone = idx < currentStepIdx;
                    const isActive = !isDone && idx === currentStepIdx;
                    return (
                      <div key={idx} className="flex flex-col items-center gap-1.5 text-center">
                        <div className={`w-5 h-5 rounded-full border text-[8px] flex items-center justify-center transition-all duration-300 ${
                          isDone
                            ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-400 font-bold"
                            : isActive
                              ? "bg-cyan-500/20 border-cyan-400 text-cyan-400 font-bold shadow-[0_0_8px_rgba(34,211,238,0.3)] animate-pulse"
                              : "bg-black/40 border-white/10 text-slate-600"
                        }`}>
                          {isDone ? "✓" : idx + 1}
                        </div>
                        <span className={`text-[7.5px] font-sans font-medium uppercase tracking-wider ${
                          isDone ? "text-emerald-400" : isActive ? "text-cyan-400 font-bold" : "text-slate-600"
                        }`}>
                          {step.label}
                        </span>
                      </div>
                    );
                  });
                })()}
              </div>
            </div>

            {/* Classification Scorecard */}
            {activeTicket.classification && (
              <div className="bg-white/[0.02] border border-white/5 rounded-2xl p-4 flex flex-col gap-3 select-none">
                <div className="flex justify-between items-center border-b border-white/5 pb-2">
                  <span className="text-[10px] font-mono uppercase tracking-widest text-slate-300 font-bold flex items-center gap-1.5">
                    <Activity className="w-3.5 h-3.5 text-cyan-400" /> Classification Analysis
                  </span>
                  <div className="flex items-center gap-2">
                    {activeTicket.classification.is_multi_domain && (
                      <span className="text-[8px] font-mono bg-amber-500/10 border border-amber-500/30 text-amber-400 px-1.5 py-0.5 rounded uppercase">
                        Multi-Domain
                      </span>
                    )}
                    <ConfidenceLevelBadge level={activeTicket.classification.confidence_level} />
                  </div>
                </div>

                <div className="flex flex-col md:flex-row items-start gap-4">
                  {/* Confidence gauge — NaN-safe guard (W-9) */}
                  <div className="relative shrink-0 flex items-center justify-center bg-black/20 rounded-xl p-3 border border-white/5 w-32 h-32">
                    <svg className="w-full h-full transform -rotate-90" viewBox="0 0 120 120">
                      <circle cx="60" cy="60" r="38" stroke="rgba(255,255,255,0.05)" strokeWidth="7" fill="transparent" />
                      <circle
                        cx="60" cy="60" r="38"
                        stroke="#22d3ee"
                        strokeWidth="7"
                        fill="transparent"
                        strokeDasharray={238.76}
                        strokeDashoffset={238.76 * (1 - (Number.isFinite(activeTicket.classification.confidence) ? activeTicket.classification.confidence : 0))}
                        strokeLinecap="round"
                        className="transition-all duration-700 ease-out"
                      />
                    </svg>
                    <div className="absolute flex flex-col items-center justify-center text-center">
                      <span className="text-lg font-mono font-bold tracking-tight text-cyan-400">
                        {((Number.isFinite(activeTicket.classification.confidence) ? activeTicket.classification.confidence : 0) * 100).toFixed(0)}%
                      </span>
                      <span className="text-[7.5px] font-mono text-slate-500 uppercase tracking-wider">Confidence</span>
                    </div>
                  </div>

                  {/* Category breakdown */}
                  <div className="flex-grow flex flex-col gap-2 w-full">
                    <div className="bg-black/30 border border-white/5 p-2 rounded-xl">
                      <span className="text-[7px] text-slate-500 uppercase block font-bold font-mono">Predicted Category</span>
                      <span className="text-sm font-semibold text-cyan-400 capitalize">
                        {activeTicket.classification.predicted_category?.replace(/_/g, " ")}
                      </span>
                    </div>
                    {activeTicket.classification.top_categories?.length > 0 && (
                      <div className="flex flex-col gap-1">
                        {activeTicket.classification.top_categories.slice(0, 3).map((tc: any, i: number) => (
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
                    <div className="text-[8px] font-mono text-slate-600">
                      Method: {activeTicket.classification.classification_method}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Resolution routing info */}
            {activeTicket.resolution && (
              <div className="bg-white/[0.02] border border-white/5 rounded-2xl p-4 flex flex-col gap-3">
                <div className="flex justify-between items-center border-b border-white/5 pb-2">
                  <span className="text-[10px] font-mono uppercase tracking-widest text-slate-300 font-bold">
                    Routing Decision
                  </span>
                  <div className="flex items-center gap-2">
                    {activeTicket.resolution.is_repeated_issue && (
                      <span className="text-[8px] font-mono bg-amber-500/10 border border-amber-500/30 text-amber-400 px-1.5 py-0.5 rounded uppercase">
                        Repeated Issue
                      </span>
                    )}
                    <span className={`text-[9px] font-mono font-bold px-2 py-0.5 rounded border uppercase ${
                      activeTicket.resolution.routing_decision === "auto_resolved"
                        ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                        : activeTicket.resolution.routing_decision === "escalated"
                          ? "bg-rose-500/10 border-rose-500/30 text-rose-400"
                          : "bg-blue-500/10 border-blue-500/30 text-blue-400"
                    }`}>
                      {activeTicket.resolution.routing_decision?.replace(/_/g, " ")}
                    </span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
                  {activeTicket.resolution.llm_quality_score != null && (
                    <div className="bg-black/30 border border-white/5 p-2 rounded-xl">
                      <span className="text-[7px] text-slate-500 uppercase block font-bold">Quality Score</span>
                      <span className="text-sm font-semibold text-amber-400">
                        {activeTicket.resolution.llm_quality_score?.toFixed(1)} / 5.0
                      </span>
                    </div>
                  )}
                  {activeTicket.resolution.assigned_department && (
                    <div className="bg-black/30 border border-white/5 p-2 rounded-xl">
                      <span className="text-[7px] text-slate-500 uppercase block font-bold">Assigned To</span>
                      <span className="text-xs font-semibold text-blue-400">
                        {activeTicket.resolution.assigned_department}
                      </span>
                    </div>
                  )}
                </div>
                {activeTicket.resolution.escalation_reason && (
                  <div className="bg-rose-950/20 border border-rose-500/20 rounded-xl p-3 text-xs text-rose-300 font-sans">
                    <span className="font-bold text-rose-400">Escalation Reason: </span>
                    {activeTicket.resolution.escalation_reason}
                  </div>
                )}
              </div>
            )}

            {/* Incident payload */}
            <div className="bg-black/30 border border-white/5 rounded-xl p-4 flex flex-col gap-2">
              <div className="flex justify-between items-center border-b border-white/5 pb-2">
                <span className="text-[10px] font-mono text-slate-400 uppercase font-bold">Masked Incident Payload</span>
                {activeTicket.pii_detected && (
                  <span className="text-[9px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded font-mono font-bold">
                    🔒 PII SCRUBBED
                  </span>
                )}
              </div>
              <p className="text-xs font-semibold text-slate-200">{activeTicket.title}</p>
              <div className="text-xs font-mono text-slate-300 bg-black/40 p-3 rounded-lg border border-white/5 whitespace-pre-wrap leading-relaxed select-text">
                {activeTicket.description}
              </div>
            </div>

            {/* Resolution steps — spinner only shows while resolution is still null (I-3) */}
            <div className="flex flex-col gap-3">
              {(() => {
                const steps = splitSteps(activeTicket.resolution?.suggested_steps);
                if (steps.length > 0) {
                  return (
                    <div className="flex flex-col gap-2.5 bg-purple-500/[0.02] border border-purple-500/10 rounded-2xl p-4">
                      <div className="flex items-center justify-between pb-2 border-b border-purple-500/10 font-mono text-[8px] text-purple-400 font-bold uppercase select-none">
                        <span>✓ AI-Generated Runbook Steps</span>
                        {activeTicket.resolution?.llm_quality_score != null && (
                          <span>Judge Score: {activeTicket.resolution.llm_quality_score?.toFixed(1)}/5</span>
                        )}
                      </div>
                      {steps.map((step, index) => (
                        <div key={index} className="flex gap-2.5 items-start text-xs leading-relaxed text-slate-300">
                          <span className="w-4.5 h-4.5 rounded-full bg-purple-500/10 border border-purple-500/25 text-violet-400 text-[9px] font-mono font-bold flex items-center justify-center shrink-0 mt-0.5">
                            {index + 1}
                          </span>
                          <p className="font-sans leading-normal pl-0.5 select-text">{step}</p>
                        </div>
                      ))}
                    </div>
                  );
                }
                if (activeTicket.resolution && !activeTicket.resolution.suggested_steps?.trim()) {
                  return (
                    <div className="border border-dashed border-rose-500/20 rounded-xl p-5 text-center bg-rose-500/[0.02] py-6 select-none">
                      <AlertTriangle className="w-5 h-5 text-rose-400 mx-auto mb-2" />
                      <p className="text-[9px] font-mono text-rose-300 uppercase tracking-widest font-bold">No Resolution Steps Available</p>
                    </div>
                  );
                }
                return (
                  <div className="border border-dashed border-white/10 rounded-xl p-5 text-center bg-white/[0.02] py-8 select-none">
                    <RefreshCw className="w-5 h-5 text-purple-400 animate-spin mx-auto mb-2" />
                    <p className="text-[9px] font-mono text-purple-300 uppercase tracking-widest font-bold">Agents compiling resolution...</p>
                  </div>
                );
              })()}
            </div>

            {/* Operator feedback */}
            <div className="mt-2 pt-4 border-t border-white/10 flex flex-col gap-3.5">
              <div className="flex items-center justify-between font-mono select-none">
                <span className="text-[9px] text-slate-300 font-bold uppercase tracking-widest">
                  Human Operator Review
                </span>
                <span className="text-[7.5px] text-slate-500">Checkout Validation</span>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-[9px] font-mono text-slate-500 uppercase select-none font-bold whitespace-nowrap">Operator ID:</span>
                <input
                  type="text"
                  value={operatorName}
                  onChange={(e) => setOperatorName(e.target.value)}
                  className="bg-black/60 border border-white/10 rounded-lg px-2.5 py-1 text-[10px] text-slate-300 focus:outline-none focus:border-cyan-500/50 font-mono w-full"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[9px] font-mono text-slate-500 uppercase font-bold select-none">
                  Edit Steps Before Committing:
                </label>
                <textarea
                  value={editedStepsText}
                  onChange={(e) => setEditedStepsText(e.target.value)}
                  rows={10}
                  className="w-full bg-slate-950/60 border border-white/10 rounded-xl p-2.5 text-[10.5px] text-slate-300 focus:outline-none focus:border-cyan-500/50 font-mono leading-relaxed"
                  style={{ resize: "vertical", minHeight: "160px" }}
                  placeholder="Edit resolution steps here before committing..."
                />
              </div>

              <div className="flex flex-col gap-2 mt-1 select-none">
                <div className="flex gap-2">
                  <button
                    onClick={() => handleResolveFeedback("accepted")}
                    disabled={feedbackSubmitting || TERMINAL_STATUSES.includes(activeTicket.status)}
                    className="flex-grow py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-white font-sans text-xs font-bold transition-all cursor-pointer disabled:opacity-35 disabled:bg-slate-800 disabled:text-slate-500 uppercase tracking-wider shadow-lg shadow-emerald-500/10"
                  >
                    {TERMINAL_STATUSES.includes(activeTicket.status) ? "✓ Committed" : "Commit & Approve"}
                  </button>
                  <button
                    onClick={() => handleResolveFeedback("modified")}
                    disabled={feedbackSubmitting || TERMINAL_STATUSES.includes(activeTicket.status) || editedStepsText.trim() === ""}
                    className="py-2 px-4 rounded-xl border border-cyan-500/40 bg-cyan-950/20 hover:bg-cyan-500/20 text-cyan-400 font-sans text-xs font-bold cursor-pointer transition-all disabled:opacity-35 disabled:text-slate-500 uppercase"
                  >
                    Save Edit
                  </button>
                </div>
                <button
                  onClick={() => handleResolveFeedback("rejected")}
                  disabled={feedbackSubmitting || activeTicket.status === "escalated"}
                  className="w-full py-1.5 border border-rose-500/20 bg-rose-950/20 text-[9px] font-mono text-rose-400 hover:text-rose-300 hover:bg-rose-500/20 rounded-xl cursor-pointer transition-all disabled:opacity-30 uppercase tracking-wider"
                >
                  Flag Incorrect / Reject Resolution
                </button>
              </div>
            </div>

          </div>
        ) : (
          <div className="glass-container border border-dashed border-white/10 rounded-2xl p-12 text-center bg-[#0d0f14]/40 select-none">
            <ShieldAlert className="w-10 h-10 text-slate-700 mx-auto mb-3 animate-pulse" />
            <h3 className="font-bold uppercase tracking-wider text-slate-400 font-mono text-xs">No Active Ticket Selected</h3>
            <p className="font-sans text-xs text-slate-500 max-w-sm mx-auto mt-2 leading-relaxed">
              Select an incident from the queue or submit a new ticket to view the AI resolution pipeline.
            </p>
          </div>
        )}
      </div>
    </motion.div>
  );
}
