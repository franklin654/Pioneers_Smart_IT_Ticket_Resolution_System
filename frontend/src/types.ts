export type TicketStatus =
  | "new"
  | "classifying"
  | "classified"
  | "awaiting_review"
  | "retrieving"
  | "generating"
  | "evaluating"
  | "auto_resolved"
  | "assigned"
  | "escalated"
  | "closed"
  | "reopened";

export type Category =
  | "infrastructure"
  | "software"
  | "hardware"
  | "network"
  | "access_management"
  | "security";

export type RoutingDecision =
  | "auto_resolved"
  | "assigned"
  | "escalated"
  | "awaiting_review";

export type FeedbackAction = "accepted" | "modified" | "rejected";

export type ConfidenceLevel = "high" | "medium" | "low";

export interface ResolutionStep {
  step_number: number;
  instruction: string;
}

export interface Classification {
  predicted_category: Category;
  confidence: number;
  confidence_level: ConfidenceLevel;
  is_multi_domain: boolean;
  top_categories: Array<{ category: Category; probability: number }>;
  classification_method: string;
}

export interface Resolution {
  routing_decision: RoutingDecision;
  suggested_steps: ResolutionStep[] | null;
  retrieved_tickets: unknown[] | null;
  llm_quality_score: number | null;
  escalation_reason: string | null;
  assigned_department: string | null;
}

export interface Ticket {
  id: string;
  title: string;
  description: string;
  category: Category | null;
  priority: number;
  status: TicketStatus;
  source: string;
  pii_detected: boolean;
  created_at: string;
  updated_at: string;
  classification: Classification | null;
  resolution: Resolution | null;
}

export interface Meta {
  total: number;
  offset: number;
  limit: number;
}

export interface ApiResponse<T> {
  data: T;
  meta?: Meta;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details: unknown[];
  };
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface IngestRequest {
  title: string;
  description: string;
  priority: number;
  category?: Category;
}

export interface IngestResponse {
  ticket_id: string;
  status: TicketStatus;
  message: string;
}
