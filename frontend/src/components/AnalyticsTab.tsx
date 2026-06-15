import React from "react";
import { motion } from "motion/react";
import {
  Activity,
  Cpu,
  CheckCircle2,
  ShieldAlert,
  Award,
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";

interface AnalyticsTabProps {
  analytics: {
    total: number;
    by_routing: { auto_resolved: number; assigned: number; escalated: number; closed: number };
    by_category: Record<string, number>;
  };
}

const CATEGORY_COLORS: Record<string, string> = {
  infrastructure: "#38bdf8",
  application: "#c084fc",
  security: "#f43f5e",
  database: "#fbbf24",
  network: "#22d3ee",
  access_management: "#a855f7",
};

export default function AnalyticsTab({ analytics }: AnalyticsTabProps) {
  if (!analytics) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3 font-mono text-slate-500 select-none">
        <span className="w-6 h-6 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
        Computing metrics...
      </div>
    );
  }

  const total = analytics.total || 0;
  // Spread with defaults to guard against partial objects (I-10)
  const byRouting = { auto_resolved: 0, assigned: 0, escalated: 0, closed: 0, ...analytics.by_routing };
  const byCategory = analytics.by_category || {};

  const autoResolveRate = total ? Math.round((byRouting.auto_resolved / total) * 100) : 0;
  const assignRate = total ? Math.round((byRouting.assigned / total) * 100) : 0;
  const escalationRate = total ? Math.round((byRouting.escalated / total) * 100) : 0;

  const categoryChartData = Object.entries(byCategory)
    .map(([key, value]) => ({
      name: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      value,
      color: CATEGORY_COLORS[key] || "#cbd5e1",
    }))
    .sort((a, b) => b.value - a.value);

  return (
    <motion.div
      key="analytics"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex flex-col gap-6 text-left w-full"
    >
      {/* KPI Bento Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="glass-container border border-white/10 rounded-2xl p-4 bg-black/45 shadow-md flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider font-semibold">Total Tickets</span>
            <span className="text-xl font-bold font-mono text-white mt-0.5">{total}</span>
            <span className="text-[8.5px] text-cyan-400 font-mono mt-1">Live count</span>
          </div>
          <Activity className="w-8 h-8 text-cyan-400 opacity-80" />
        </div>

        <div className="glass-container border border-white/10 rounded-2xl p-4 bg-black/45 shadow-md flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider font-semibold">AI Auto-Resolve</span>
            <span className="text-xl font-bold font-mono text-emerald-400 mt-0.5">{autoResolveRate}%</span>
            <span className="text-[8.5px] text-slate-400 font-mono mt-1">{byRouting.auto_resolved} resolved</span>
          </div>
          <CheckCircle2 className="w-8 h-8 text-emerald-400 opacity-80" />
        </div>

        <div className="glass-container border border-white/10 rounded-2xl p-4 bg-black/45 shadow-md flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider font-semibold">Assigned L1/L2</span>
            <span className="text-xl font-bold font-mono text-blue-400 mt-0.5">{assignRate}%</span>
            <span className="text-[8.5px] text-slate-400 font-mono mt-1">{byRouting.assigned} assigned</span>
          </div>
          <Cpu className="w-8 h-8 text-blue-400 opacity-80" />
        </div>

        <div className="glass-container border border-white/10 rounded-2xl p-4 bg-black/45 shadow-md flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider font-semibold">Escalations</span>
            <span className="text-xl font-bold font-mono text-rose-400 mt-0.5">{escalationRate}%</span>
            <span className="text-[8.5px] text-rose-500/80 font-mono mt-1">{byRouting.escalated} escalated</span>
          </div>
          <ShieldAlert className="w-8 h-8 text-rose-400 opacity-80" />
        </div>
      </div>

      {/* Note about data source */}
      <div className="text-[9px] font-mono text-slate-500 bg-white/[0.02] border border-white/5 rounded-xl px-3 py-2 select-none">
        Showing live counts computed from active ticket data. Historical daily charts are not available without a dedicated analytics endpoint.
      </div>

      {/* Category breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-container border border-white/10 rounded-2xl p-5 bg-black/40 shadow-xl flex flex-col gap-4">
          <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest font-bold">
            Incidents by Domain
          </span>
          {categoryChartData.length > 0 ? (
            <div className="w-full h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={categoryChartData} margin={{ top: 5, right: 5, left: -25, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.01)" vertical={false} />
                  <XAxis dataKey="name" stroke="#475569" fontSize={8} fontFamily="monospace" tickLine={false} />
                  <YAxis stroke="#475569" fontSize={9} fontFamily="monospace" tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "rgba(2, 4, 10, 0.95)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "12px" }}
                    itemStyle={{ fontSize: "11px", color: "#e2e8f0" }}
                  />
                  <Bar dataKey="value" name="Tickets">
                    {categoryChartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex items-center justify-center h-40 text-slate-600 font-mono text-xs">
              No category data yet.
            </div>
          )}
        </div>

        <div className="glass-container border border-white/10 rounded-2xl p-5 bg-black/40 shadow-xl flex flex-col gap-4">
          <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest font-bold">
            Routing Breakdown
          </span>
          <div className="flex flex-col gap-4 justify-center flex-grow">
            {[
              { label: "Auto Resolved", value: byRouting.auto_resolved, color: "#10b981" },
              { label: "Assigned", value: byRouting.assigned, color: "#3b82f6" },
              { label: "Escalated", value: byRouting.escalated, color: "#f43f5e" },
              { label: "Closed", value: byRouting.closed, color: "#64748b" },
            ].map((item, idx) => {
              const pct = total ? Math.round((item.value / total) * 100) : 0;
              return (
                <div key={idx} className="flex flex-col gap-1 pr-2">
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-mono text-slate-400 text-[11px] font-bold uppercase">{item.label}</span>
                    <span className="font-mono text-slate-500">{item.value} ({pct}%)</span>
                  </div>
                  <div className="w-full h-2 rounded bg-white/5 overflow-hidden">
                    <div
                      className="h-full rounded transition-all duration-500"
                      style={{ width: `${pct}%`, backgroundColor: item.color }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
