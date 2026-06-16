import { useEffect, useLayoutEffect, useRef, useCallback } from "react";
import type { TicketStatus } from "../../../types";

interface WsEvent {
  event: "status_changed" | "done" | "error";
  ticket_id: string;
  status?: TicketStatus;
  detail?: string;
}

interface Options {
  ticketId: string | null;
  onStatusChange: (status: TicketStatus) => void;
  onDone: (status: TicketStatus) => void;
  onError?: (detail: string) => void;
}

export function useWebSocket({ ticketId, onStatusChange, onDone, onError }: Options) {
  // Use refs for callbacks to avoid stale-closure re-subscriptions
  const onStatusChangeRef = useRef(onStatusChange);
  const onDoneRef = useRef(onDone);
  const onErrorRef = useRef(onError);
  // Keep refs in sync after each render so the WS handler always has fresh callbacks
  useLayoutEffect(() => {
    onStatusChangeRef.current = onStatusChange;
    onDoneRef.current = onDone;
    onErrorRef.current = onError;
  });

  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback((id: string) => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/tickets/${id}`);
    wsRef.current = ws;

    ws.onmessage = (e: MessageEvent<string>) => {
      const msg = JSON.parse(e.data) as WsEvent;
      if (msg.event === "status_changed" && msg.status) {
        onStatusChangeRef.current(msg.status);
      } else if (msg.event === "done" && msg.status) {
        onDoneRef.current(msg.status);
      } else if (msg.event === "error") {
        onErrorRef.current?.(msg.detail ?? "Unknown error");
      }
    };

    ws.onerror = () => {
      onErrorRef.current?.("WebSocket connection error.");
    };

    return ws;
  }, []);

  useEffect(() => {
    if (!ticketId) return;
    const ws = connect(ticketId);
    return () => ws.close();
  }, [ticketId, connect]);

  return wsRef;
}
