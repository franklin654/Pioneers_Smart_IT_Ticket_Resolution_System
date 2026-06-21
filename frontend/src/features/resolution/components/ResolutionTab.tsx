import { useEffect, useState, useCallback } from "react";
import type { Category, ResolutionStep, TicketStatus } from "../../../types";
import { useTickets } from "../hooks/useTickets";
import { useWebSocket } from "../hooks/useWebSocket";
import { ClassificationPanel } from "../../../shared/components/ClassificationPanel";
import { RoutingPanel } from "../../../shared/components/RoutingPanel";
import { ReclassifyPanel } from "./ReclassifyPanel";
import { PIPELINE_STEPS, STATUS_STEP_MAP, STATUS_LABELS } from "../../../shared/constants";
import { formatDate, priorityLabel, priorityColor } from "../../../shared/utils";

interface FeedbackState {
  action: "accepted" | "modified" | "rejected" | null;
  modified: ResolutionStep[];
  submitted: boolean;
}

function PipelineStepper({ status }: { status: TicketStatus }) {
  const step = STATUS_STEP_MAP[status];
  return (
    <ol
      aria-label="Pipeline progress"
      className="flex items-center gap-0 text-xs"
    >
      {PIPELINE_STEPS.map((label, i) => (
        <li key={label} className="flex items-center">
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full border text-xs font-bold ${
              i < step
                ? "border-indigo-500 bg-indigo-500 text-white"
                : i === step
                  ? "border-indigo-400 text-indigo-300"
                  : "border-slate-600 text-slate-500"
            }`}
            aria-current={i === step ? "step" : undefined}
          >
            {i + 1}
          </span>
          <span
            className={`mx-1 hidden sm:inline ${i === step ? "text-indigo-300 font-medium" : "text-slate-500"}`}
          >
            {label}
          </span>
          {i < PIPELINE_STEPS.length - 1 && (
            <span className="mx-1 text-slate-600">›</span>
          )}
        </li>
      ))}
    </ol>
  );
}

interface Props {
  initialTicketId?: string | null;
}

export function ResolutionTab({ initialTicketId }: Props = {}) {
  const {
    tickets,
    activeTicket,
    loading,
    error,
    fetchTickets,
    selectTicket,
    refreshActiveTicket,
    reclassifyTicket,
    sendFeedback,
    setActiveTicket,
  } = useTickets();

  const [wsTicketId, setWsTicketId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<FeedbackState>({ action: null, modified: [], submitted: false });

  useEffect(() => {
    void fetchTickets();
  }, [fetchTickets]);

  // Auto-select ticket when navigated from Ticket Search
  useEffect(() => {
    if (initialTicketId) {
      void handleSelect(initialTicketId);
    }
    // Only run when initialTicketId changes, not on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTicketId]);

  const handleStatusChange = useCallback(
    (status: TicketStatus) => {
      setActiveTicket((prev) => (prev ? { ...prev, status } : prev));
    },
    [setActiveTicket],
  );

  const handleDone = useCallback(() => {
    void refreshActiveTicket();
    setWsTicketId(null);
    void fetchTickets();
  }, [refreshActiveTicket, fetchTickets]);

  useWebSocket({
    ticketId: wsTicketId,
    onStatusChange: handleStatusChange,
    onDone: handleDone,
  });

  async function handleSelect(id: string) {
    await selectTicket(id);
    setWsTicketId(id);
    setFeedback({ action: null, modified: [], submitted: false });
  }

  async function handleReclassify(cat: Category) {
    await reclassifyTicket(cat);
    setWsTicketId(activeTicket?.id ?? null);
  }

  // Feedback buttons only show when a resolution exists but hasn't been
  // acted on yet. Once the ticket is closed (accepted/modified) or
  // the user explicitly rejected it (escalated by their own action),
  // the server state is the source of truth — local feedback state is not.
  const awaitingFeedback = activeTicket
    ? activeTicket.status === "auto_resolved" || activeTicket.status === "assigned"
    : false;

  return (
    <div className="flex h-full gap-4" style={{ minHeight: "60vh" }}>
      {/* Ticket list */}
      <aside className="w-64 shrink-0 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-2">
        <h2 className="mb-2 px-2 text-xs font-semibold uppercase tracking-widest text-slate-500">
          Tickets
        </h2>
        {loading && (
          <p className="px-2 text-sm text-slate-500" aria-live="polite">
            Loading…
          </p>
        )}
        {error && (
          <p className="px-2 text-sm text-rose-400" role="alert">
            {error}
          </p>
        )}
        <ul role="list">
          {tickets.map((t) => (
            <li key={t.id}>
              <button
                onClick={() => void handleSelect(t.id)}
                className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  activeTicket?.id === t.id
                    ? "bg-indigo-600/30 text-indigo-200"
                    : "text-slate-300 hover:bg-slate-700/50"
                }`}
                aria-current={activeTicket?.id === t.id ? "true" : undefined}
              >
                <p className="truncate font-medium">{t.title}</p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {STATUS_LABELS[t.status]}
                </p>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Detail panel */}
      <main className="flex-1 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-6 space-y-6">
        {!activeTicket ? (
          <p className="text-slate-500">Select a ticket to view details.</p>
        ) : (
          <>
            {/* Header */}
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-4">
                <h2 className="text-lg font-semibold text-slate-100">
                  {activeTicket.title}
                </h2>
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium bg-${priorityColor(activeTicket.priority)}-500/20 text-${priorityColor(activeTicket.priority)}-300`}
                >
                  {priorityLabel(activeTicket.priority)}
                </span>
              </div>
              <p className="text-xs text-slate-500">
                {formatDate(activeTicket.created_at)}
              </p>
            </div>

            {/* Pipeline stepper */}
            <PipelineStepper status={activeTicket.status} />

            {/* Description */}
            <p className="text-sm text-slate-300">{activeTicket.description}</p>

            {/* Classification */}
            {activeTicket.classification && (
              <div className="rounded-lg border border-[var(--color-border)] bg-slate-800/50 p-4 space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500">
                  Classification
                </h3>
                <ClassificationPanel classification={activeTicket.classification} />
              </div>
            )}

            {/* Awaiting review → reclassify */}
            {activeTicket.status === "awaiting_review" && (
              <ReclassifyPanel
                escalationReason={activeTicket.resolution?.escalation_reason ?? null}
                onSubmit={handleReclassify}
              />
            )}

            {/* Resolution */}
            {activeTicket.resolution &&
              activeTicket.status !== "awaiting_review" && (
                <div className="rounded-lg border border-[var(--color-border)] bg-slate-800/50 p-4 space-y-4">
                  <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500">
                    Resolution
                  </h3>
                  <RoutingPanel resolution={activeTicket.resolution} />

                  {activeTicket.resolution.suggested_steps && (
                    <ol
                      aria-label="Resolution steps"
                      className="space-y-2 text-sm"
                    >
                      {activeTicket.resolution.suggested_steps.map((s) => (
                        <li
                          key={s.step_number}
                          className="flex gap-3 rounded-lg bg-slate-700/40 px-3 py-2"
                        >
                          <span className="shrink-0 font-mono text-indigo-400">
                            {s.step_number}.
                          </span>
                          <span className="text-slate-200">{s.instruction}</span>
                        </li>
                      ))}
                    </ol>
                  )}

                  {/* Feedback — only while ticket still awaits a decision */}
                  {awaitingFeedback && !feedback.action && (
                    <div
                      className="flex gap-2"
                      role="group"
                      aria-label="Resolution feedback"
                    >
                      <button
                        onClick={async () => {
                          await sendFeedback("accepted");
                          setFeedback((f) => ({ ...f, action: "accepted", submitted: true }));
                        }}
                        className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                      >
                        Accept
                      </button>
                      <button
                        onClick={() =>
                          setFeedback({
                            action: "modified",
                            modified: activeTicket.resolution?.suggested_steps ?? [],
                            submitted: false,
                          })
                        }
                        className="rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500"
                      >
                        Modify
                      </button>
                      <button
                        onClick={async () => {
                          await sendFeedback("rejected");
                          setFeedback((f) => ({ ...f, action: "rejected", submitted: true }));
                        }}
                        className="rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-500 focus:outline-none focus:ring-2 focus:ring-rose-500"
                      >
                        Reject
                      </button>
                    </div>
                  )}

                  {/* Inline step editor for Modify */}
                  {awaitingFeedback && feedback.action === "modified" && !feedback.submitted && (
                    <div className="space-y-3">
                      <p className="text-xs font-semibold uppercase tracking-widest text-amber-400">
                        Edit resolution steps
                      </p>
                      {feedback.modified.map((step, idx) => (
                        <div key={idx} className="flex gap-2 items-start">
                          <span className="shrink-0 mt-2 font-mono text-indigo-400 text-sm w-5 text-right">
                            {idx + 1}.
                          </span>
                          <textarea
                            rows={2}
                            value={step.instruction}
                            onChange={(e) =>
                              setFeedback((f) => ({
                                ...f,
                                modified: f.modified.map((s, i) =>
                                  i === idx ? { ...s, instruction: e.target.value } : s,
                                ),
                              }))
                            }
                            className="flex-1 rounded-lg bg-slate-700 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-amber-500 resize-none"
                          />
                          <button
                            onClick={() =>
                              setFeedback((f) => {
                                const next = f.modified
                                  .filter((_, i) => i !== idx)
                                  .map((s, i) => ({ ...s, step_number: i + 1 }));
                                return { ...f, modified: next };
                              })
                            }
                            aria-label="Delete step"
                            className="shrink-0 mt-1.5 rounded px-2 py-1 text-xs text-rose-400 hover:bg-rose-500/20 focus:outline-none focus:ring-2 focus:ring-rose-500"
                          >
                            ✕
                          </button>
                        </div>
                      ))}
                      <button
                        onClick={() =>
                          setFeedback((f) => ({
                            ...f,
                            modified: [
                              ...f.modified,
                              { step_number: f.modified.length + 1, instruction: "" },
                            ],
                          }))
                        }
                        className="text-xs text-amber-400 hover:text-amber-300 focus:outline-none focus:underline"
                      >
                        + Add step
                      </button>
                      <div className="flex gap-2 pt-1">
                        <button
                          onClick={async () => {
                            await sendFeedback("modified", feedback.modified);
                            setFeedback((f) => ({ ...f, submitted: true }));
                          }}
                          className="rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500"
                        >
                          Submit changes
                        </button>
                        <button
                          onClick={() => setFeedback({ action: null, modified: [], submitted: false })}
                          className="rounded-lg bg-slate-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-400"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Confirmation after feedback submitted this session */}
                  {feedback.submitted && (
                    <p className="text-sm text-emerald-400">
                      {feedback.action === "accepted" && "✓ Resolution accepted — ticket closed."}
                      {feedback.action === "modified" && "✓ Modified resolution submitted — ticket closed."}
                      {feedback.action === "rejected" && "✓ Resolution rejected — ticket escalated for review."}
                    </p>
                  )}

                  {/* Status banner on reload — server is source of truth */}
                  {!awaitingFeedback && !feedback.submitted && (
                    activeTicket.status === "closed" ? (
                      <p className="text-sm text-slate-400">Resolution was accepted — ticket is closed.</p>
                    ) : activeTicket.status === "escalated" ? (
                      <p className="text-sm text-slate-400">Resolution was rejected — ticket escalated for review.</p>
                    ) : null
                  )}
                </div>
              )}
          </>
        )}
      </main>
    </div>
  );
}
