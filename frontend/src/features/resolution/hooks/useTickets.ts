import { useState, useCallback } from "react";
import {
  listTickets,
  getTicket,
  submitFeedback,
  reclassifyTicket as apiReclassify,
} from "../../../api/client";
import type { Category, Ticket, ResolutionStep } from "../../../types";

export function useTickets() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [activeTicket, setActiveTicket] = useState<Ticket | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTickets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { tickets: list } = await listTickets({ limit: 15 });
      setTickets(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tickets.");
    } finally {
      setLoading(false);
    }
  }, []);

  const selectTicket = useCallback(async (id: string) => {
    try {
      const t = await getTicket(id);
      setActiveTicket(t);
    } catch {
      setError("Failed to load ticket.");
    }
  }, []);

  const refreshActiveTicket = useCallback(async () => {
    if (!activeTicket) return;
    const t = await getTicket(activeTicket.id);
    setActiveTicket(t);
    setTickets((prev) => prev.map((x) => (x.id === t.id ? t : x)));
  }, [activeTicket]);

  const reclassifyTicket = useCallback(
    async (category: Category) => {
      if (!activeTicket) return;
      await apiReclassify(activeTicket.id, category);
    },
    [activeTicket],
  );

  const sendFeedback = useCallback(
    async (
      action: "accepted" | "modified" | "rejected",
      modified?: ResolutionStep[],
    ) => {
      if (!activeTicket) return;
      await submitFeedback(activeTicket.id, action, modified);
      await refreshActiveTicket();
    },
    [activeTicket, refreshActiveTicket],
  );

  return {
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
  };
}
