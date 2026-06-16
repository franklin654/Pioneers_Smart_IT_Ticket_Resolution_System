import type { TicketStatus, Category } from "../types";

export const TERMINAL_STATUSES: readonly TicketStatus[] = [
  "auto_resolved",
  "assigned",
  "escalated",
  "closed",
];

export const STATUS_STEP_MAP: Record<TicketStatus, number> = {
  new: 0,
  classifying: 1,
  classified: 1,
  awaiting_review: 1,
  retrieving: 2,
  generating: 3,
  evaluating: 4,
  auto_resolved: 5,
  assigned: 5,
  escalated: 5,
  closed: 5,
  reopened: 0,
};

export const STATUS_LABELS: Record<TicketStatus, string> = {
  new: "New",
  classifying: "Classifying",
  classified: "Classified",
  awaiting_review: "Awaiting Review",
  retrieving: "Retrieving",
  generating: "Generating",
  evaluating: "Evaluating",
  auto_resolved: "Auto-Resolved",
  assigned: "Assigned",
  escalated: "Escalated",
  closed: "Closed",
  reopened: "Reopened",
};

export const STATUS_COLORS: Partial<Record<TicketStatus, string>> = {
  auto_resolved: "emerald",
  assigned: "blue",
  escalated: "rose",
  awaiting_review: "amber",
  new: "slate",
  classifying: "violet",
  retrieving: "violet",
  generating: "violet",
  evaluating: "violet",
};

export const CATEGORIES: Category[] = [
  "infrastructure",
  "software",
  "hardware",
  "network",
  "access_management",
  "security",
];

export const DOMAIN_STYLES: Record<Category, { label: string; color: string }> = {
  infrastructure: { label: "Infrastructure", color: "blue" },
  software: { label: "Software", color: "violet" },
  hardware: { label: "Hardware", color: "orange" },
  network: { label: "Network", color: "cyan" },
  access_management: { label: "Access Mgmt", color: "green" },
  security: { label: "Security", color: "rose" },
};

export const PIPELINE_STEPS = [
  "Queued",
  "Classify",
  "Retrieve",
  "Generate",
  "Evaluate",
  "Done",
];
