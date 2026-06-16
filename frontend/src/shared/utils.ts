import type { TicketStatus } from "../types";
import { TERMINAL_STATUSES } from "./constants";

export function isTerminal(status: TicketStatus): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(status);
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function priorityLabel(p: number): string {
  return ["", "Critical", "High", "Medium", "Low", "Minimal"][p] ?? "Unknown";
}

export function priorityColor(p: number): string {
  return (
    ["", "rose", "orange", "amber", "blue", "slate"][p] ?? "slate"
  );
}
