import React, { useEffect, useRef, useState, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Cpu,
  Clock,
  Send,
  RefreshCw,
  Activity,
  Terminal,
  ListChecks,
  BookOpen,
  LogOut,
} from "lucide-react";
import LoginForm from "./components/LoginForm";
import IntakeTab from "./components/IntakeTab";
import ResolutionTab from "./components/ResolutionTab";
import AgentTab from "./components/AgentTab";
import KBTab from "./components/KBTab";
import AnalyticsTab from "./components/AnalyticsTab";

const PRIORITY_MAP: Record<string, number> = {
  critical: 1, high: 2, medium: 3, low: 4, informational: 5,
};

export default function App() {
  // Auth
  const [accessToken, setAccessToken] = useState<string | null>(() =>
    sessionStorage.getItem("ticketiq_token")
  );

  // Tickets
  const [ticketsList, setTicketsList] = useState<any[]>([]);
  const [activeTicketId, setActiveTicketId] = useState<string | null>(null);
  const [activeTicket, setActiveTicket] = useState<any | null>(null);
  const [isPolling, setIsPolling] = useState(false);

  // Form inputs
  const [formTitle, setFormTitle] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formPriority, setFormPriority] = useState("high");
  const [formCategory, setFormCategory] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Operator feedback
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [editedStepsText, setEditedStepsText] = useState("");
  const [operatorName, setOperatorName] = useState("Staff Operator #090");

  // Particle explode trigger
  const [triggerDecompose, setTriggerDecompose] = useState(false);

  // Clock
  const [timeStr, setTimeStr] = useState("");

  // Navigation
  const [activeTab, setActiveTab] = useState<"intake" | "resolution" | "reasoning" | "cases" | "analytics">("intake");

  // Notices
  const [notice, setNotice] = useState<{ type: "info" | "error"; text: string } | null>(null);

  // Resolved cases (replaces KB/FAQ)
  const [resolvedCases, setResolvedCases] = useState<any[]>([]);
  const [casesLoading, setCasesLoading] = useState(false);

  // Refs: keep activeTicketId accessible inside WS closure (C-5), track decompose timer (W-3)
  const activeTicketIdRef = useRef<string | null>(activeTicketId);
  const decomposeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { activeTicketIdRef.current = activeTicketId; }, [activeTicketId]);

  // Cleanup decompose timer on unmount (W-3)
  useEffect(() => () => {
    if (decomposeTimerRef.current) clearTimeout(decomposeTimerRef.current);
  }, []);

  // Analytics computed from ticket list — includes "closed" (W-8)
  const computedAnalytics = useMemo(() => {
    const total = ticketsList.length;
    const byRouting = { auto_resolved: 0, assigned: 0, escalated: 0, closed: 0 };
    const byCategory: Record<string, number> = {};
    ticketsList.forEach((t) => {
      const s = t.status as string;
      if (s === "auto_resolved" || s === "assigned" || s === "escalated" || s === "closed") {
        byRouting[s as keyof typeof byRouting]++;
      }
      const cat = t.category || "unknown";
      byCategory[cat] = (byCategory[cat] || 0) + 1;
    });
    return { total, by_routing: byRouting, by_category: byCategory };
  }, [ticketsList]);

  // UTC clock
  useEffect(() => {
    const update = () =>
      setTimeStr(new Date().toISOString().replace("T", " // ").slice(0, 19) + " UTC");
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);

  const handleLoginSuccess = (token: string) => {
    sessionStorage.setItem("ticketiq_token", token);
    setAccessToken(token);
  };

  const handleLogout = () => {
    sessionStorage.removeItem("ticketiq_token");
    setAccessToken(null);
    setTicketsList([]);
    setActiveTicket(null);
    setActiveTicketId(null);
  };

  // Initial data load after login
  useEffect(() => {
    if (!accessToken) return;
    fetchTickets();
    fetchResolvedCases();
  }, [accessToken]);

  // Refresh ticket list whenever the resolution tab is active
  useEffect(() => {
    if (activeTab !== "resolution" || !accessToken) return;
    fetchTickets();
    const id = setInterval(fetchTickets, 15000);
    return () => clearInterval(id);
  }, [activeTab, accessToken]);

  // Sync edited steps when ticket changes
  useEffect(() => {
    if (activeTicket?.resolution?.suggested_steps) {
      setEditedStepsText(activeTicket.resolution.suggested_steps);
    } else {
      setEditedStepsText("");
    }
  }, [activeTicketId, activeTicket?.resolution]);

  // Hydrate full ticket detail when selection changes
  useEffect(() => {
    if (!activeTicketId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/v1/tickets/${activeTicketId}`);
        if (res.ok && !cancelled) {
          const full = await res.json();
          setActiveTicket(full);
        }
      } catch (e) {
        console.error("Ticket hydration failed", e);
      }
    })();
    return () => { cancelled = true; };
  }, [activeTicketId]);

  // WebSocket for live status updates — uses ref to avoid stale activeTicketId closure (C-5)
  useEffect(() => {
    if (!isPolling || !activeTicketId) return;
    let ws: WebSocket | null = null;

    try {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${protocol}//${window.location.host}/ws/tickets/${activeTicketId}`);

      ws.onmessage = async (event) => {
        try {
          const msg = JSON.parse(event.data);
          const currentId = activeTicketIdRef.current;
          if (msg.event === "status_changed" || msg.event === "done") {
            const res = await fetch(`/api/v1/tickets/${currentId}`);
            if (res.ok) setActiveTicket(await res.json());
          }
          if (msg.event === "done") {
            setIsPolling(false);
            fetchTickets();
            ws?.close();
          }
          if (msg.event === "error") {
            setIsPolling(false);
            setNotice({ type: "error", text: msg.message || "WebSocket error" });
            ws?.close();
          }
        } catch (e) {
          console.warn("WS: malformed message received", e);
        }
      };

      ws.onerror = () => {
        console.warn("WS error — status updates may be delayed");
      };
    } catch (err) {
      console.warn("Could not connect WebSocket", err);
    }

    return () => { ws?.close(); };
  }, [isPolling, activeTicketId]);

  const fetchTickets = async (skipAutoSelectFor?: string) => {
    try {
      const res = await fetch("/api/v1/tickets/?limit=100");
      // Auto-logout on expired/invalid token (W-2)
      if (res.status === 401) {
        handleLogout();
        return;
      }
      if (res.ok) {
        const data = await res.json();
        const items = data.items || [];
        setTicketsList(items);
        if (items.length > 0 && !skipAutoSelectFor && !activeTicketId) {
          setActiveTicketId(items[0].id);
          setActiveTicket(items[0]);
        }
      }
    } catch (e) {
      console.error("Ticket list fetch failed", e);
    }
  };

  const fetchResolvedCases = async () => {
    setCasesLoading(true);
    try {
      const res = await fetch("/api/v1/tickets/?status=auto_resolved&limit=50");
      if (res.ok) {
        const data = await res.json();
        setResolvedCases(data.items || []);
      }
    } catch (e) {
      console.error("Resolved cases fetch failed", e);
    } finally {
      setCasesLoading(false);
    }
  };

  // Wrapped particle trigger that clears any pending reset timer (W-3)
  const fireDecomposeAndReset = () => {
    setTriggerDecompose(true);
    if (decomposeTimerRef.current) clearTimeout(decomposeTimerRef.current);
    decomposeTimerRef.current = setTimeout(() => setTriggerDecompose(false), 500);
  };

  // Ticket selection with unsaved-edits guard (W-5)
  const handleSelectTicket = (ticketId: string, ticket: any) => {
    const originalSteps = activeTicket?.resolution?.suggested_steps ?? "";
    if (editedStepsText !== originalSteps) {
      if (!window.confirm("You have unsaved resolution edits. Switch tickets and discard changes?")) {
        return;
      }
    }
    setActiveTicketId(ticketId);
    setActiveTicket(ticket);
  };

  const handleTicketIngestion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formTitle.trim() || !formDesc.trim()) return;
    setSubmitting(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

      const priorityInt = PRIORITY_MAP[formPriority.toLowerCase()] ?? 2;

      const res = await fetch("/api/v1/tickets/ingest", {
        method: "POST",
        headers,
        body: JSON.stringify({
          title: formTitle,
          description: formDesc,
          priority: priorityInt,
          ...(formCategory ? { category: formCategory } : {}),
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (res.ok) {
        setActiveTicketId(data.ticket_id);
        setIsPolling(true);
        // Reset all form fields including priority and category (C-8)
        setFormTitle("");
        setFormDesc("");
        setFormPriority("high");
        setFormCategory("");
        fireDecomposeAndReset();
        fetchTickets(data.ticket_id);
        setActiveTab("resolution");
        setNotice(null);
      } else if (res.status === 409 && data?.detail?.existing_ticket_id) {
        setIsPolling(false);
        setActiveTicketId(data.detail.existing_ticket_id);
        setActiveTab("resolution");
        setNotice({
          type: "info",
          text: `Duplicate detected (${data.detail.duplicate_type || "exact"} match). Showing existing resolution.`,
        });
        fetchTickets();
      } else if (res.status === 401) {
        handleLogout();
      } else {
        setNotice({
          type: "error",
          text: data?.detail || data?.message || `Submission failed (HTTP ${res.status}).`,
        });
      }
    } catch (err) {
      setNotice({ type: "error", text: "Cannot reach the backend. Is the FastAPI server running?" });
    } finally {
      setSubmitting(false);
    }
  };

  const selectPresetScenario = (preset: any) => {
    setFormTitle(preset.title);
    setFormDesc(preset.desc);
    setFormPriority(preset.priority || "high");
    setFormCategory(preset.cat || "");
  };

  const handleResolveFeedback = async (type: "accepted" | "modified" | "rejected") => {
    if (!activeTicket) return;
    const ticketId = activeTicket.id;
    setFeedbackSubmitting(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

      const res = await fetch(`/api/v1/resolutions/${ticketId}/feedback`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          action: type,
          ...(type === "modified" ? { modified_resolution: editedStepsText } : {}),
        }),
      });

      if (res.ok || res.status === 204) {
        fireDecomposeAndReset();
        await fetchTickets();
        fetchResolvedCases();
        const updated = await fetch(`/api/v1/tickets/${ticketId}`);
        if (updated.ok) setActiveTicket(await updated.json());
      } else if (res.status === 401) {
        handleLogout();
      }
    } catch (err) {
      console.error("Feedback submit failed", err);
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  if (!accessToken) {
    return <LoginForm onSuccess={handleLoginSuccess} />;
  }

  return (
    <div className="relative min-h-screen font-sans bg-[#02040a] text-slate-100 flex flex-col overflow-x-hidden selection:bg-cyan-500/30">

      {/* Ambient background */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className="absolute top-[-10%] right-[-10%] w-[700px] h-[700px] bg-cyan-500/5 rounded-full blur-[140px]" />
        <div className="absolute bottom-[-10%] left-[-10%] w-[600px] h-[600px] bg-purple-600/5 rounded-full blur-[120px]" />
        <div className="cyber-grid absolute inset-0 opacity-40" />
        <div className="cyber-scanline absolute top-0 w-full" />
      </div>

      {/* HEADER */}
      <header className="relative z-20 w-full glass-container border-b border-white/5 bg-black/45 backdrop-blur-md px-6 py-3.5 flex flex-col lg:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-400 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <Cpu className="w-5.5 h-5.5 text-white animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-display font-semibold tracking-wide uppercase">TicketIQ</h1>
              <span className="text-[9px] bg-cyan-500/15 text-cyan-400 border border-cyan-500/20 px-2 py-0.5 rounded font-mono tracking-wider font-bold">
                AUTONOMOUS COGNITIVE CORE
              </span>
            </div>
            <p className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
              Multi-Agent IT Dispatch & Generative Auto-Resolution Framework
            </p>
          </div>
        </div>

        {/* Navigation */}
        <div className="flex flex-wrap gap-1 bg-white/5 border border-white/10 p-1 rounded-2xl relative z-10 pointer-events-auto max-w-full overflow-x-auto">
          {[
            { id: "intake", label: "Incident Ingest Desk", icon: Send },
            { id: "resolution", label: "Triage & Resolution Board", icon: ListChecks },
            { id: "reasoning", label: "AI Analysis & Sandbox", icon: Terminal },
            { id: "cases", label: "Resolved Cases Reference", icon: BookOpen },
            { id: "analytics", label: "Telemetry & Health Metrics", icon: Activity },
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center gap-2 py-2 px-3.5 rounded-xl text-xs font-mono uppercase tracking-wider transition-all cursor-pointer whitespace-nowrap ${
                  isActive
                    ? "bg-cyan-500/15 text-cyan-400 border border-cyan-500/40 font-bold shadow-inner"
                    : "bg-transparent text-slate-400 border border-transparent hover:text-slate-200"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Clock & logout */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 glass-pill px-4 py-1.5 rounded-xl border border-white/10 font-mono text-[10px] text-slate-400">
            <Clock className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
            <span>{timeStr || "Aligning UTC clocks..."}</span>
          </div>
          <div className="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1.5 rounded-xl">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-[9px] font-mono font-bold text-emerald-400 uppercase tracking-widest">LIVE</span>
          </div>
          <button
            onClick={handleLogout}
            title="Sign out"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-white/10 text-slate-400 hover:text-rose-400 hover:border-rose-500/30 transition-all text-[10px] font-mono uppercase tracking-wider"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </header>

      {/* Notice banner */}
      {notice && (
        <div className="relative z-20 max-w-[1800px] w-full mx-auto px-4 mt-3">
          <div className={`flex items-center justify-between gap-3 rounded-xl border px-4 py-2.5 text-xs font-mono ${
            notice.type === "error"
              ? "border-rose-500/40 bg-rose-950/30 text-rose-300"
              : "border-cyan-500/40 bg-cyan-950/30 text-cyan-300"
          }`}>
            <span>{notice.text}</span>
            <button
              onClick={() => setNotice(null)}
              className="text-current/70 hover:text-current font-bold px-2 cursor-pointer select-none"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Main content */}
      <main className="relative z-10 flex-grow max-w-[1800px] w-full mx-auto px-4 py-4 flex flex-col overflow-hidden items-stretch">
        <AnimatePresence mode="wait">
          {activeTab === "intake" && (
            <IntakeTab
              formTitle={formTitle}
              setFormTitle={setFormTitle}
              formDesc={formDesc}
              setFormDesc={setFormDesc}
              formPriority={formPriority}
              setFormPriority={setFormPriority}
              formCategory={formCategory}
              setFormCategory={setFormCategory}
              submitting={submitting}
              handleTicketIngestion={handleTicketIngestion}
              selectPresetScenario={selectPresetScenario}
            />
          )}

          {activeTab === "resolution" && (
            <ResolutionTab
              ticketsList={ticketsList}
              activeTicketId={activeTicketId}
              onSelectTicket={handleSelectTicket}
              activeTicket={activeTicket}
              isPolling={isPolling}
              editedStepsText={editedStepsText}
              setEditedStepsText={setEditedStepsText}
              operatorName={operatorName}
              setOperatorName={setOperatorName}
              handleResolveFeedback={handleResolveFeedback}
              feedbackSubmitting={feedbackSubmitting}
            />
          )}

          {activeTab === "reasoning" && (
            <AgentTab
              activeTicket={activeTicket}
              isPolling={isPolling}
              triggerDecompose={triggerDecompose}
              setTriggerDecompose={setTriggerDecompose}
            />
          )}

          {activeTab === "cases" && (
            <KBTab
              cases={resolvedCases}
              loading={casesLoading}
              onRefresh={fetchResolvedCases}
            />
          )}

          {activeTab === "analytics" && (
            <AnalyticsTab analytics={computedAnalytics} />
          )}
        </AnimatePresence>
      </main>

      {/* Footer stats bar */}
      <footer className="relative z-10 w-full px-4 pb-4">
        <div className="glass-container border border-white/5 bg-black/40 backdrop-blur-md rounded-2xl px-6 py-3 shadow-xl flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400 animate-pulse" />
            <span className="text-[10px] uppercase font-mono tracking-widest text-slate-400 font-bold">
              Live System Overview
            </span>
          </div>
          <div className="flex items-center gap-6 font-mono text-[9px]">
            {[
              { label: "Total", value: computedAnalytics.total, color: "text-white" },
              { label: "Auto-Resolved", value: computedAnalytics.by_routing.auto_resolved, color: "text-emerald-400" },
              { label: "Assigned", value: computedAnalytics.by_routing.assigned, color: "text-blue-400" },
              { label: "Escalated", value: computedAnalytics.by_routing.escalated, color: "text-rose-400" },
              { label: "Closed", value: computedAnalytics.by_routing.closed, color: "text-slate-400" },
            ].map(({ label, value, color }) => (
              <div key={label} className="flex flex-col items-center gap-0.5">
                <span className={`font-bold text-xs ${color}`}>{value}</span>
                <span className="text-slate-500 uppercase tracking-widest text-[7px]">{label}</span>
              </div>
            ))}
          </div>
          <button
            onClick={fetchTickets}
            className="flex items-center gap-1.5 text-[9px] font-mono text-slate-400 hover:text-cyan-400 transition-colors uppercase tracking-wider"
          >
            <RefreshCw className="w-3 h-3" /> Refresh
          </button>
        </div>
      </footer>
    </div>
  );
}
