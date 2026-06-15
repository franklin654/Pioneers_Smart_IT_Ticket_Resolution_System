import React from "react";
import { motion } from "motion/react";
import { Send, RefreshCw, Shield } from "lucide-react";

interface IntakeTabProps {
  formTitle: string;
  setFormTitle: (v: string) => void;
  formDesc: string;
  setFormDesc: (v: string) => void;
  formPriority: string;
  setFormPriority: (v: string) => void;
  formCategory: string;
  setFormCategory: (v: string) => void;
  submitting: boolean;
  handleTicketIngestion: (e: React.FormEvent) => void;
  selectPresetScenario: (preset: any) => void;
}

const PRESETS = [
  {
    label: "SQL Timeout",
    title: "Orders index table scanning locks",
    desc: "Order dashboard reporting fails with analytical database full sequential index scan over 10M rows.",
    priority: "high",
    cat: "database",
  },
  {
    label: "Brute Force",
    title: "Invalid SSH handshake cluster flags",
    desc: "Edge Firewall logs flag sequential unauthorized access commands targeting system administrator endpoints from IP 185.220.101.5.",
    priority: "critical",
    cat: "security",
  },
  {
    label: "Node Eviction",
    title: "Web node disk pressure crash",
    desc: "kubelet logs show production pod evictions on prod-web-01 cluster. Out of storage warning.",
    priority: "high",
    cat: "infrastructure",
  },
];

export default function IntakeTab({
  formTitle,
  setFormTitle,
  formDesc,
  setFormDesc,
  formPriority,
  setFormPriority,
  formCategory,
  setFormCategory,
  submitting,
  handleTicketIngestion,
  selectPresetScenario,
}: IntakeTabProps) {
  return (
    <motion.div
      key="intake"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start w-full text-left"
    >
      {/* Left: intake form */}
      <div className="lg:col-span-7 flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-mono text-cyan-400 uppercase tracking-widest font-bold">
            Telemetry Dispatch Core
          </span>
          <h2 className="text-xl font-semibold tracking-tight text-white">
            Report New Telemetry Incident
          </h2>
          <p className="text-xs text-slate-400">
            Input system symptoms, warning configurations, or select a predefined scenario preset below to trigger the multi-agent AI verification resolve path.
          </p>
        </div>

        <div className="glass-container border border-white/10 rounded-2xl p-5 bg-black/45 shadow-xl">
          <form onSubmit={handleTicketIngestion} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <label className="text-[9px] font-mono font-bold text-slate-400 uppercase tracking-wider">
                Incident Summary Title
              </label>
              <input
                type="text"
                placeholder="e.g. Orders database cluster slow scan locks..."
                value={formTitle}
                onChange={(e) => setFormTitle(e.target.value)}
                maxLength={200}
                className="bg-black/60 border border-white/10 rounded-xl py-2 px-3 text-xs text-white focus:border-cyan-400/50 transition-all focus:outline-none placeholder-slate-600 shadow-inner"
                required
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-[9px] font-mono font-bold text-slate-400 uppercase tracking-wider">
                  Priority Level
                </label>
                <select
                  value={formPriority}
                  onChange={(e) => setFormPriority(e.target.value)}
                  className="bg-black/60 border border-white/10 rounded-xl py-2 px-2.5 text-xs font-mono text-slate-300 focus:outline-none cursor-pointer"
                >
                  <option value="low">Low (P4)</option>
                  <option value="medium">Medium (P3)</option>
                  <option value="high">High (P2)</option>
                  <option value="critical">Critical (P1)</option>
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[9px] font-mono font-bold text-slate-400 uppercase tracking-wider">
                  Target System Domain
                </label>
                <select
                  value={formCategory}
                  onChange={(e) => setFormCategory(e.target.value)}
                  className="bg-black/60 border border-white/10 rounded-xl py-2 px-2.5 text-xs font-mono text-slate-300 focus:outline-none cursor-pointer"
                >
                  <option value="">AI Auto-Classification</option>
                  <option value="infrastructure">Infrastructure</option>
                  <option value="application">Application</option>
                  <option value="security">Security</option>
                  <option value="database">Database</option>
                  <option value="access_management">Access Management</option>
                  <option value="network">Network</option>
                </select>
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-[9px] font-mono font-bold text-slate-400 uppercase tracking-wider">
                Raw Symptoms Payload
              </label>
              <textarea
                placeholder="Paste telemetry tracebacks, client variables, JSON database configs, error logs..."
                value={formDesc}
                onChange={(e) => setFormDesc(e.target.value)}
                maxLength={5000}
                className="bg-black/60 border border-white/10 rounded-xl p-3 text-xs text-white focus:outline-none h-28 resize-none font-mono placeholder-slate-600 shadow-inner leading-relaxed"
                required
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-2.5 bg-gradient-to-r from-cyan-400 to-blue-500 hover:scale-[1.01] active:scale-[0.99] transition-all text-white rounded-xl text-xs uppercase font-mono font-bold flex items-center justify-center gap-2 cursor-pointer disabled:opacity-40"
            >
              {submitting ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Ingesting Telemetry...
                </>
              ) : (
                <>
                  <Send className="w-3 h-3" /> Commit & Run Resolution Pipeline
                </>
              )}
            </button>
          </form>
        </div>
      </div>

      {/* Right: scenarios & privacy */}
      <div className="lg:col-span-5 flex flex-col gap-6">
        <div className="glass-container border border-white/10 bg-black/40 rounded-2xl p-4 shadow-lg flex flex-col gap-3">
          <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider font-bold">
            Scenario Sandbox Templates
          </span>
          <p className="text-xs text-slate-400 leading-normal">
            Click a preset to populate the form with a realistic infrastructure incident.
          </p>
          <div className="flex flex-col gap-2.5">
            {PRESETS.map((preset, index) => (
              <button
                key={index}
                onClick={() => selectPresetScenario(preset)}
                className="p-3 bg-white/5 border border-white/5 rounded-xl text-left hover:border-cyan-400/30 hover:bg-cyan-950/10 cursor-pointer group transition-all"
              >
                <div className="flex justify-between items-center mb-0.5">
                  <span className="text-xs font-semibold text-slate-200 group-hover:text-cyan-400 transition-colors">
                    {preset.label}
                  </span>
                  <span className="text-[8px] bg-cyan-400/10 text-cyan-400 px-1.5 py-0.5 rounded font-mono uppercase">
                    {preset.cat}
                  </span>
                </div>
                <p className="text-[10.5px] text-slate-400 truncate leading-normal">
                  {preset.title}: {preset.desc}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div className="glass-container border border-emerald-500/20 bg-emerald-950/5 rounded-2xl p-4 shadow-lg flex flex-col gap-3">
          <div className="flex items-center gap-2 border-b border-emerald-500/10 pb-2">
            <Shield className="w-4 h-4 text-emerald-400" />
            <h3 className="text-xs uppercase font-mono tracking-wider text-emerald-400 font-bold">
              Privacy Shield Protected
            </h3>
          </div>
          <p className="text-xs text-slate-300 leading-normal">
            All transaction fields, database secrets, passwords, credentials and emails are automatically scrubbed server-side <strong>before</strong> any data reaches downstream AI modules.
          </p>
          <div className="flex flex-col gap-1.5 font-mono text-[9px] text-slate-400 bg-black/40 border border-white/5 p-2.5 rounded-xl">
            <div className="flex items-center gap-2">
              <span className="text-emerald-400">✔</span>
              <span><strong>Client Emails</strong> → [REDACTED_EMAIL]</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-emerald-400">✔</span>
              <span><strong>API Keys &amp; Passwords</strong> fully stripped</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-emerald-400">✔</span>
              <span><strong>IP Addresses</strong> → [REDACTED_IP]</span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
